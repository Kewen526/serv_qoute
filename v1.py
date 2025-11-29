import requests
import json
import time
import base64
import os
from urllib import parse
from PIL import Image
from io import BytesIO
from datetime import datetime, timedelta

# ==================== 禁用系统代理 ====================
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

# ==================== 配置信息 ====================
# Service Points API配置
SP_API_KEY = "5d47f1b2b5e485ad2f46d05264d6db4f"
SP_BASE_URL = "https://app.servicepoints.nl/api/v2"

# 内部API配置
INTERNAL_API_URL = "http://47.95.157.46:8520/api/up-sp-bj"
INTERNAL_NON_QUOTABLE_URL = "http://47.95.157.46:8520/api/up-sp-bj_copy_9LotzZVQ"  # 标记不可报价任务接口
SAVE_TASK_URL = "http://47.95.157.46:8520/api/task-data/save"
GET_MESSAGE_URL = "http://47.95.157.46:8520/api/product-attributes"
GET_TASK_DETAIL_URL = "http://47.95.157.46:8520/api/getTaskDetailById"
GET_PRODUCT_INFO_URL = "http://47.95.157.46:8520/api/get_product_info"
UPDATE_SP_STATUS_URL = "http://47.95.157.46:8520/api/up_sp_status"  # ✅ 新增：更新SP状态接口

# 报价人员名称到店铺代码前缀的映射
SUPPLIER_NAME_TO_CODE = {
    "Yu Liu": "LPP-SP00001",
    "Panpan Liu (1)": "LYN-SP00001",
    "Liu Lila": "QY-SP00001",
    "XU Liam": "LDD-SP00001",
    "Liu Hong": "SQQ-SP00001",
    "Li Yanshuang": "LYS-SP00001",
    "Xuelian qi": "SJL-SP00002",
    "Sain xu": "LY-SP00002"
}

# 默认消息内容
DEFAULT_MESSAGE = ("Your quotation has been completed. We are waiting for the supplier to provide product "
                   "real-shot pictures and the size chart, which will ensure we offer you the most accurate "
                   "and clear product information. We will upload them as soon as we receive the physical "
                   "product images from the factory. Thank you for your understanding.")

# 国家代码映射（处理不同格式的国家代码）
COUNTRY_CODE_MAPPING = {
    "UK/GB": "GB",
    "UK": "GB",
    "United Kingdom": "GB",
    "USA": "US",
    "United States": "US",
    "UAE": "AE",
    "Australia": "AU",
    "New Zealand": "NZ",
    "Ireland": "IE",
    "Canada": "CA",
    "Singapore": "SG"
}

# 循环配置
LOOP_INTERVAL = 30  # 每轮循环完成后等待时间（秒），30秒


# ==================== 日期处理函数 ====================

def get_date_list():
    """
    获取需要处理的日期列表：今天、昨天、前天
    返回格式：["2025-11-20", "2025-11-19", "2025-11-18"]
    """
    today = datetime.now()
    date_list = []

    for i in range(3):  # 今天、昨天、前天
        date = today - timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        date_list.append(date_str)

    return date_list


# ==================== 内部API函数 ====================

def parse_task_data(result):
    """
    解析任务数据
    新格式: {"data": [0, [claimed], 1, [tasks]], ...}
    旧格式: {"data": [[tasks]], ...} 或 {"data": [tasks], ...}
    """
    if not result or not result.get('success'):
        return []

    tasks_data = result.get('data', [])

    if not tasks_data or not isinstance(tasks_data, list):
        return []

    # 新格式：data是 [0, [...], 1, [...]] 这种形式
    if len(tasks_data) >= 4 and isinstance(tasks_data[3], list):
        task_list = tasks_data[3]
        if task_list and isinstance(task_list[0], dict):
            return task_list

    # 旧格式1：data是 [[task1, task2, ...]]
    if len(tasks_data) > 0 and isinstance(tasks_data[0], list):
        task_list = tasks_data[0]
        if task_list and isinstance(task_list[0], dict):
            return task_list

    # 旧格式2：data直接是 [task1, task2, ...]
    if len(tasks_data) > 0 and isinstance(tasks_data[0], dict):
        return tasks_data

    return []


def get_internal_tasks(store_code, created_at):
    """
    获取内部待报价任务
    """
    headers = {
        'Content-Type': 'application/json'
    }

    payload = {
        "store_code": store_code,
        "created_at": created_at
    }

    try:
        response = requests.post(INTERNAL_API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"获取内部任务失败: {e}")
        return None


def get_non_quotable_tasks(store_code, created_at):
    """
    获取标记不可报价任务
    """
    headers = {
        'Content-Type': 'application/json'
    }

    payload = {
        "store_code": store_code,
        "created_at": created_at
    }

    try:
        response = requests.post(INTERNAL_NON_QUOTABLE_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"获取标记不可报价任务失败: {e}")
        return None


def get_product_id_by_keer_id(keer_product_id):
    """
    通过Keer产品ID获取product_id和supplier_name

    参数:
        keer_product_id: Keer产品ID

    返回:
        成功: {"success": True, "data": [{"product_id": xxx, "supplier_name": "xxx"}], ...}
        失败: None 或 {"success": False, ...}
    """
    url = "http://47.95.157.46:8520/api/sp_productid"
    headers = {
        'Content-Type': 'application/json'
    }

    payload = {
        "keep_product_id": int(keer_product_id)
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"调用Keer产品ID接口失败: {e}")
        return None


def save_task_status(keer_product_id, sp_status=None, quotation_feedback_status=None, shi_image_note=None):
    """
    保存任务状态到内部系统

    quotation_feedback_status:
    1 = 回传成功(报价成功 + 消息成功)
    2 = 回传失败(报价失败)
    3 = 价格成功消息失败(报价成功 + 消息失败)
    4 = 价格失败消息成功(报价失败 + 消息成功)
    """
    headers = {
        'Content-Type': 'application/json'
    }

    payload = {
        "keer_product_id": str(keer_product_id)
    }

    if sp_status is not None:
        payload["sp_status"] = sp_status
    if quotation_feedback_status is not None:
        payload["quotation_feedback_status"] = quotation_feedback_status
    if shi_image_note is not None:
        payload["shi_image_note"] = shi_image_note

    try:
        response = requests.post(SAVE_TASK_URL, headers=headers, json=payload, timeout=30)
        print(f"📝 保存任务状态: {response.status_code}")
        print(f"   响应: {response.text}")
        return response.status_code == 200
    except Exception as e:
        print(f"❌ 保存任务状态失败: {e}")
        return False


def update_sp_status(keer_product_id):
    """
    ✅ 新增函数：更新SP状态为已完成

    参数:
        keer_product_id: Keer产品ID

    返回:
        bool: 更新成功返回True，失败返回False
    """
    headers = {
        'Content-Type': 'application/json'
    }

    payload = {
        "id": int(keer_product_id),
        "sp_status": 2  # 固定值2
    }

    try:
        print(f"\n🔄 调用update_sp_status接口...")
        print(f"   URL: {UPDATE_SP_STATUS_URL}")
        print(f"   参数: {json.dumps(payload, ensure_ascii=False)}")

        response = requests.post(UPDATE_SP_STATUS_URL, headers=headers, json=payload, timeout=30)

        print(f"   📥 响应状态: {response.status_code}")
        print(f"   📥 响应内容: {response.text}")

        if response.status_code == 200:
            print(f"   ✅ SP状态更新成功!")
            return True
        else:
            print(f"   ⚠️  SP状态更新失败: HTTP {response.status_code}")
            return False

    except Exception as e:
        print(f"   ❌ SP状态更新异常: {e}")
        return False


def get_message_content(keer_product_id):
    """
    获取消息内容
    """
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    form_data = {
        "id": str(keer_product_id)
    }
    data = parse.urlencode(form_data, True)

    try:
        response = requests.post(GET_MESSAGE_URL, headers=headers, data=data, timeout=30)
        response.raise_for_status()
        result = response.json()

        if result.get('success') and result.get('data'):
            message = result['data'][0].get('product_attribute', '').strip()
            if message:
                print(f"   ✅ 获取到自定义消息（长度: {len(message)}）")
                return message
            else:
                print(f"   ℹ️  消息为空，使用默认消息")
                return DEFAULT_MESSAGE
        else:
            print(f"   ⚠️  获取消息失败，使用默认消息")
            return DEFAULT_MESSAGE

    except Exception as e:
        print(f"   ❌ 获取消息异常: {e}，使用默认消息")
        return DEFAULT_MESSAGE


def get_uploaded_images(keer_product_id):
    """
    获取已上传的图片记录
    """
    headers = {
        'Content-Type': 'application/json'
    }

    payload = {
        "keer_product_id": str(keer_product_id)
    }

    try:
        response = requests.post(GET_TASK_DETAIL_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()

        if result.get('success') and result.get('data'):
            shi_image_note = result['data'][0].get('shi_image_note', '')
            if shi_image_note and shi_image_note != 'null':
                return shi_image_note.strip()
        return ''

    except Exception as e:
        print(f"   ❌ 获取已上传图片记录失败: {e}")
        return ''


def get_all_product_images(keer_product_id):
    """
    获取所有产品实拍图
    """
    headers = {
        'Content-Type': 'application/json'
    }

    payload = {
        "id": str(keer_product_id)
    }

    try:
        response = requests.post(GET_PRODUCT_INFO_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()

        if result.get('success') and result.get('data'):
            product_shi_img = result['data'][0].get('product_shi_img', '')
            if product_shi_img and product_shi_img != 'null':
                return product_shi_img.strip()
        return ''

    except Exception as e:
        print(f"   ❌ 获取产品实拍图失败: {e}")
        return ''


def calculate_new_images(all_images_str, uploaded_images_str):
    """
    计算待上传的新图片
    """
    if not all_images_str:
        return []

    # 支持中英文逗号分割
    all_images_str = all_images_str.replace('，', ',')
    all_images = [img.strip() for img in all_images_str.split(',') if img.strip()]

    if not uploaded_images_str:
        return all_images

    # 支持中英文逗号分割
    uploaded_images_str = uploaded_images_str.replace('，', ',')
    uploaded_images = [img.strip() for img in uploaded_images_str.split(',') if img.strip()]
    new_images = [img for img in all_images if img not in uploaded_images]

    return new_images


def download_and_encode_image(image_url, index, max_retries=3):
    """
    下载图片并转换为base64（支持所有格式包括AVIF）

    支持的输入格式：PNG, JPG, GIF, WEBP, AVIF, BMP等
    输出格式：PNG（透明）或 JPG（不透明）
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate',
        'Referer': 'https://www.1688.com/',
        'Connection': 'keep-alive',
    }

    def detect_image_format(data):
        """
        通过文件头检测真实图片格式
        """
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            return 'PNG'
        elif data.startswith(b'\xff\xd8\xff'):
            return 'JPEG'
        elif data.startswith(b'GIF87a') or data.startswith(b'GIF89a'):
            return 'GIF'
        elif data.startswith(b'RIFF') and data[8:12] == b'WEBP':
            return 'WEBP'
        elif b'ftypavif' in data[:20] or b'ftypavis' in data[:20]:
            return 'AVIF'
        elif data.startswith(b'BM'):
            return 'BMP'
        else:
            return 'UNKNOWN'

    for attempt in range(1, max_retries + 1):
        try:
            print(f"      下载图片 {index} (尝试 {attempt}/{max_retries}): {image_url[:60]}...")

            response = requests.get(
                image_url,
                headers=headers,
                timeout=30,
                allow_redirects=True
            )
            response.raise_for_status()

            # 检测真实图片格式
            detected_format = detect_image_format(response.content)
            print(f"      🔍 检测到格式: {detected_format}")

            # 如果检测到AVIF格式，尝试URL转换
            if detected_format == 'AVIF':
                print(f"      🔄 检测到AVIF格式，尝试URL转换...")

                # 尝试多种URL转换方式
                conversion_methods = []

                if '_!!' in image_url:
                    conversion_methods.append(image_url.replace('_!!', '.jpg_!!'))

                if '?' in image_url:
                    conversion_methods.append(f"{image_url}&x-oss-process=image/format,jpg")
                else:
                    conversion_methods.append(f"{image_url}?x-oss-process=image/format,jpg")

                converted_successfully = False

                for converted_url in conversion_methods:
                    try:
                        print(f"      🔗 尝试转换URL: {converted_url[:80]}...")

                        conv_response = requests.get(
                            converted_url,
                            headers=headers,
                            timeout=30,
                            allow_redirects=True
                        )
                        conv_response.raise_for_status()

                        conv_format = detect_image_format(conv_response.content)
                        print(f"      📋 转换后格式: {conv_format}")

                        if conv_format != 'AVIF':
                            print(f"      ✅ 转换成功: AVIF → {conv_format}")
                            response = conv_response
                            detected_format = conv_format
                            converted_successfully = True
                            break

                    except Exception as conv_error:
                        print(f"      ⚠️  转换失败: {conv_error}")
                        continue

                if not converted_successfully:
                    print(f"      ❌ 所有转换方式都失败")
                    if attempt < max_retries:
                        time.sleep(2 * attempt)
                        continue
                    return None

            # 使用PIL打开图片
            try:
                img = Image.open(BytesIO(response.content))

                # 检查是否有透明通道
                has_alpha = img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info)

                # 决定输出格式
                if has_alpha:
                    output_format = 'PNG'
                    ext = 'png'
                    mime_type = 'image/png'

                    if img.mode != 'RGBA':
                        img = img.convert('RGBA')
                else:
                    output_format = 'JPEG'
                    ext = 'jpg'
                    mime_type = 'image/jpeg'

                    if img.mode != 'RGB':
                        img = img.convert('RGB')

                # 保存到内存
                output_buffer = BytesIO()
                if output_format == 'JPEG':
                    img.save(output_buffer, format=output_format, quality=95, optimize=True)
                else:
                    img.save(output_buffer, format=output_format, optimize=True)

                output_buffer.seek(0)
                converted_data = output_buffer.read()

                # 转换为base64
                image_base64 = base64.b64encode(converted_data).decode('utf-8')

                filename = f"image{index}.{ext}"

                if detected_format != output_format:
                    print(f"      🔄 已转换: {detected_format} → {output_format}")

                print(f"      ✅ 图片 {index} 处理成功 (格式: {output_format}, 大小: {len(converted_data)} bytes)")

                return {
                    "name": filename,
                    "data": image_base64,
                    "type": mime_type
                }

            except Exception as pil_error:
                print(f"      ❌ PIL处理失败: {pil_error}")

                if attempt < max_retries:
                    time.sleep(2 * attempt)
                    continue
                return None

        except requests.exceptions.RequestException as e:
            print(f"      ⚠️  下载尝试 {attempt} 失败: {e}")
            if attempt < max_retries:
                wait_time = 2 * attempt
                print(f"      ⏳ 等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
            else:
                print(f"      ❌ 所有下载尝试均失败")
                return None
        except Exception as e:
            print(f"      ❌ 处理失败: {e}")
            if attempt < max_retries:
                time.sleep(2 * attempt)
                continue
            return None

    return None


def normalize_country_code(country_code):
    """
    标准化国家代码
    例如: "UK/GB" -> "GB"
    """
    if not country_code:
        return country_code

    # 去除空格并转换为大写
    country_code = country_code.strip().upper()

    # 使用映射表转换
    return COUNTRY_CODE_MAPPING.get(country_code, country_code)


# ==================== Service Points API函数 ====================

def search_products_by_title(api_key, search_keyword, is_quotation_product=2):
    """
    根据产品标题搜索产品
    """
    url = f"{SP_BASE_URL}/get-products"
    headers = {
        "X-Service-Point-Access-Token": api_key,
        "Content-Type": "application/json"
    }

    payload = {
        "is_quotation_product": is_quotation_product,
        "product_search_keys": search_keyword,
        "page": 1
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"搜索产品失败: {e}")
        return None


def mark_product_non_quotable(api_key, product_id, shopify_product_id):
    """
    标记产品为不可报价

    返回值：
    - (True, message) : 成功
    - (False, message) : 失败
    """
    headers = {
        "X-Service-Point-Access-Token": api_key,
        "Content-Type": "application/json"
    }

    # 只使用两种最可能成功的请求格式
    payload_formats = [
        # 格式1
        {
            "product_id": int(product_id),
            "shopify_product_id": int(shopify_product_id),
            "is_quotation_product": 2,
            "is_quotable": 0
        },
        # 格式3
        {
            "product_id": int(product_id),
            "shopify_product_id": int(shopify_product_id),
            "is_quotation_product": 2,
            "quotation_status": "not_available"
        }
    ]

    print(f"\n🔍 尝试标记产品不可报价...")

    endpoint = f"{SP_BASE_URL}/mark-product-non-quotable"

    # 尝试每种格式
    for idx, payload in enumerate(payload_formats, 1):
        try:
            print(f"\n   📡 尝试请求格式 #{idx}")

            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=30
            )

            print(f"   📥 响应状态: {response.status_code}")

            # 如果不是404或405，说明endpoint存在
            if response.status_code not in [404, 405]:
                try:
                    result = response.json()
                    print(f"   📥 响应内容: {json.dumps(result, ensure_ascii=False)}")

                    if result.get('success'):
                        print(f"   ✅ 标记成功!")
                        return (True, "标记成功")
                    else:
                        error_message = result.get('message', '未知错误')
                        print(f"   ⚠️  API返回: {error_message}")

                        # 特殊处理：产品已报价的情况
                        if "Quotation already given" in error_message:
                            print(f"   ℹ️  产品已有报价，无法标记为不可报价")
                            return (False, "产品已报价，无法标记不可报价")

                except json.JSONDecodeError:
                    print(f"   ⚠️  响应不是有效的JSON")
                    continue

        except Exception as e:
            print(f"   ⚠️  请求失败: {e}")
            continue

    print(f"\n   ❌ 所有尝试均失败")
    return (False, "所有API调用均失败")


def match_product_by_store(products, store_code):
    """
    根据店铺编码和报价人员匹配产品

    匹配逻辑：
    1. 从产品的 supplier_detail.name 获取报价人员名称
    2. 使用 SUPPLIER_NAME_TO_CODE 映射转换为代码前缀
    3. 将代码前缀与产品的 store 字段组合 (用 - 连接)
    4. 与任务的 store_code 进行匹配

    示例：
    - supplier_name = "Liu Hong" → code_prefix = "SQQ-SP00001"
    - product_store = "pqf5ud-v0"
    - combined = "SQQ-SP00001-pqf5ud-v0"
    - 匹配 store_code = "SQQ-SP00001-pqf5ud-v0"
    """
    if not products or not store_code:
        return None

    print(f"\n🔍 开始匹配店铺编码: {store_code}")

    # 方法1: 使用报价人员名称匹配 (优先级最高)
    for product in products:
        # 获取报价人员名称
        supplier_detail = product.get('supplier_detail', {})
        supplier_name = supplier_detail.get('name', '') if isinstance(supplier_detail, dict) else ''
        product_store = product.get('store', '')

        if supplier_name and supplier_name in SUPPLIER_NAME_TO_CODE:
            # 获取代码前缀
            code_prefix = SUPPLIER_NAME_TO_CODE[supplier_name]
            # 组合完整的店铺代码
            combined_store_code = f"{code_prefix}-{product_store}"

            print(f"   🔍 产品: {product.get('product_id')}")
            print(f"      报价人员: {supplier_name}")
            print(f"      代码前缀: {code_prefix}")
            print(f"      产品店铺: {product_store}")
            print(f"      组合代码: {combined_store_code}")

            # 完全匹配
            if combined_store_code == store_code:
                print(f"   ✅ 完全匹配!")
                return product

            # 部分匹配（任务store_code以组合代码开头）
            if store_code.startswith(combined_store_code):
                print(f"   ✅ 前缀匹配!")
                return product

    print(f"   ⚠️  未通过报价人员匹配到产品，尝试传统匹配...")

    # 方法2: 传统匹配方法（作为后备）
    store_parts = store_code.split('-')
    matched_products = []

    for product in products:
        product_store = product.get('store', '')

        if store_code == product_store:
            print(f"   ✅ 完全匹配: {product_store}")
            return product

        is_match = False
        for part in store_parts:
            if part and len(part) > 3 and part in product_store:
                is_match = True
                break

        if is_match:
            matched_products.append(product)
            print(f"   ✓ 部分匹配: {product_store}")

    if matched_products:
        print(f"   → 使用第一个匹配的产品")
        return matched_products[0]

    print(f"   ⚠️  未找到匹配的店铺，使用第一个产品")
    return products[0] if products else None


def get_product_quotation(api_key, product_id, is_quotation_product=2, is_attachment_needed=1):
    """
    获取产品详细报价信息
    """
    url = f"{SP_BASE_URL}/get-product-quotation"
    headers = {
        "X-Service-Point-Access-Token": api_key,
        "Content-Type": "application/json"
    }

    payload = {
        "product_id": product_id,
        "is_quotation_product": is_quotation_product,
        "is_attachment_needed": is_attachment_needed
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"获取产品详情失败: {e}")
        return None


def update_product_quotation(api_key, quotation_data):
    """
    更新/回传产品报价
    """
    url = f"{SP_BASE_URL}/update-product-quotation"
    headers = {
        "X-Service-Point-Access-Token": api_key,
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, headers=headers, json=quotation_data, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"更新报价失败: {e}")
        return None


def send_product_message(api_key, message_data, image_files=None):
    """
    发送产品消息和图片
    """
    url = f"{SP_BASE_URL}/save-product-chat-messages"
    headers = {
        "X-Service-Point-Access-Token": api_key,
        "Content-Type": "application/json"
    }

    payload = {
        "product_id": message_data['product_id'],
        "quotation_id": message_data['quotation_id'],
        "client_account_id": message_data['client_account_id'],
        "client_user_id": message_data['client_user_id'],
        "quotation_request_id": message_data['quotation_request_id'],
        "is_quotation_product": 2,
        "shopify_product_id": message_data['shopify_product_id'],
        "description": message_data['description']
    }

    if image_files:
        payload["myProductfiles"] = image_files

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"发送消息失败: {e}")
        return None


# ==================== 国家代码映射 ====================

def get_country_id_mapping(quotation_info):
    """
    从quotation_information中提取国家代码映射
    """
    country_mapping = {}

    if not quotation_info or not isinstance(quotation_info, dict):
        return country_mapping

    for country_code, variants in quotation_info.items():
        if variants and len(variants) > 0:
            country_id = variants[0].get('country_id')
            if country_id:
                country_mapping[country_code] = country_id

    return country_mapping


# ==================== 核心处理函数 ====================

def process_non_quotable_task(task_data):
    """
    处理标记不可报价任务
    """
    print("\n" + "=" * 100)
    print("开始处理标记不可报价任务")
    print("=" * 100)

    # 1. 提取任务信息
    client_product_title = task_data.get('client_product_title')
    store_code = task_data.get('store_code')
    keer_product_id = task_data.get('keer_product_id')

    if not client_product_title:
        print("❌ 错误: 缺少产品标题")
        return False

    if not keer_product_id:
        print("❌ 错误: 缺少keer_product_id")
        return False

    print(f"\n📦 产品标题: {client_product_title}")
    print(f"🏪 店铺代码: {store_code}")
    print(f"🆔 Keer产品ID: {keer_product_id}")

    # 2. 通过Keer产品ID获取product_id
    print(f"\n🔍 通过Keer产品ID获取product_id...")
    keer_result = get_product_id_by_keer_id(keer_product_id)

    if not keer_result or not keer_result.get('success'):
        print(f"❌ Keer产品ID接口调用失败")
        save_task_status(
            keer_product_id=keer_product_id,
            sp_status="Keer产品ID接口调用失败",
            quotation_feedback_status=2
        )
        return False

    data = keer_result.get('data', [])
    if not data:
        print(f"❌ Keer产品ID接口返回空数据")
        save_task_status(
            keer_product_id=keer_product_id,
            sp_status="Keer产品ID接口返回空数据",
            quotation_feedback_status=2
        )
        return False

    product_id = data[0].get('product_id')

    if not product_id:
        print(f"❌ 未获取到product_id")
        save_task_status(
            keer_product_id=keer_product_id,
            sp_status="未获取到product_id",
            quotation_feedback_status=2
        )
        return False

    print(f"✅ 获取到product_id: {product_id}")

    # 3. 获取产品详情以获取shopify_product_id
    print(f"\n📋 获取产品详细信息...")
    detail_result = get_product_quotation(SP_API_KEY, product_id, is_attachment_needed=0)

    if not detail_result or not detail_result.get('success'):
        print(f"❌ 获取产品详情失败")
        save_task_status(
            keer_product_id=keer_product_id,
            sp_status="获取产品详情失败",
            quotation_feedback_status=2
        )
        return False

    detail_data = detail_result.get('data', [])
    if not detail_data:
        print(f"❌ 产品详情为空")
        save_task_status(
            keer_product_id=keer_product_id,
            sp_status="产品详情为空",
            quotation_feedback_status=2
        )
        return False

    product_detail = detail_data[0]
    shopify_product_id = product_detail.get('product_shopify_id')

    print(f"✅ 获取到产品详情")
    print(f"   Product ID: {product_id}")
    print(f"   Shopify ID: {shopify_product_id}")

    # 4. 标记产品不可报价
    print(f"\n🚫 正在标记产品为不可报价...")
    success, message = mark_product_non_quotable(SP_API_KEY, product_id, shopify_product_id)

    if not success:
        print(f"\n❌ 标记失败: {message}")

        # 根据不同的失败原因保存不同的状态
        if "产品已报价" in message:
            save_task_status(
                keer_product_id=keer_product_id,
                sp_status="产品已报价，无法标记不可报价",
                quotation_feedback_status=2
            )
        else:
            save_task_status(
                keer_product_id=keer_product_id,
                sp_status="标记不可报价失败",
                quotation_feedback_status=2
            )
        return False

    print(f"\n✅✅✅ 标记成功! ✅✅✅")

    # 5. 保存成功状态
    print(f"\n📝 保存成功状态...")
    save_task_status(
        keer_product_id=keer_product_id,
        quotation_feedback_status=1
    )

    # ✅ 6. 调用update_sp_status接口
    update_sp_status(keer_product_id)

    print(f"\n🎉🎉🎉 标记不可报价任务处理完成! 🎉🎉🎉")
    return True


def process_quotation_task(task_data):
    """
    处理单个报价任务
    """
    print("\n" + "=" * 100)
    print("开始处理报价任务")
    print("=" * 100)

    # 1. 提取任务信息
    client_product_title = task_data.get('client_product_title')
    quotation_result_str = task_data.get('quotation_result')
    store_code = task_data.get('store_code')
    keer_product_id = task_data.get('keer_product_id')

    if not client_product_title:
        print("❌ 错误: 缺少产品标题")
        return False

    if not quotation_result_str:
        print("❌ 错误: 缺少报价结果")
        return False

    if not keer_product_id:
        print("❌ 错误: 缺少keer_product_id")
        return False

    print(f"📦 产品标题: {client_product_title}")
    print(f"🏪 店铺代码: {store_code}")
    print(f"🆔 Keer产品ID: {keer_product_id}")

    # 2. 解析报价结果
    try:
        quotation_result = json.loads(quotation_result_str)
        print(f"📊 报价数量: {len(quotation_result)} 条")

        valid_quotes = [q for q in quotation_result if q.get('price', 0) > 0]
        zero_price_quotes = [q for q in quotation_result if q.get('price', 0) == 0]

        print(f"   ✅ 有效报价: {len(valid_quotes)} 条")
        if zero_price_quotes:
            print(f"   ⚠️  跳过价格为0的报价: {len(zero_price_quotes)} 条")

        # ✅ 如果所有价格都是0，标记失败
        if len(valid_quotes) == 0:
            print(f"\n❌ 所有报价价格都为0，无法回传")
            save_task_status(
                keer_product_id=keer_product_id,
                sp_status="价格全为0，无法回传",
                quotation_feedback_status=2
            )
            return False

        print("\n💰 报价详情（显示前20条）:")
        display_count = min(20, len(quotation_result))
        for i in range(display_count):
            quote = quotation_result[i]
            price_status = "✅" if quote.get('price', 0) > 0 else "❌跳过"
            original_nation = quote.get('nation')
            normalized_nation = normalize_country_code(original_nation)
            nation_display = f"{original_nation} -> {normalized_nation}" if original_nation != normalized_nation else original_nation
            print(f"   {i + 1}. {price_status} 国家:{nation_display} | 数量:{quote.get('quantity')} | "
                  f"价格:{quote.get('price')} | 利润:{quote.get('profit')}")

        if len(quotation_result) > 20:
            print(f"   ... 还有 {len(quotation_result) - 20} 条报价未显示")

    except json.JSONDecodeError as e:
        print(f"❌ 错误: 解析报价结果失败 - {e}")
        return False

    # 3. 通过Keer产品ID获取product_id和supplier_name
    print(f"\n🔍 通过Keer产品ID获取product_id...")
    keer_result = get_product_id_by_keer_id(keer_product_id)

    if not keer_result or not keer_result.get('success'):
        print(f"❌ Keer产品ID接口调用失败")
        save_task_status(
            keer_product_id=keer_product_id,
            sp_status="Keer产品ID接口调用失败",
            quotation_feedback_status=2
        )
        return False

    data = keer_result.get('data', [])
    if not data:
        print(f"❌ Keer产品ID接口返回空数据")
        save_task_status(
            keer_product_id=keer_product_id,
            sp_status="Keer产品ID接口返回空数据",
            quotation_feedback_status=2
        )
        return False

    product_id = data[0].get('product_id')
    supplier_name_from_keer = data[0].get('supplier_name')  # 保存这个用于后续对比

    if not product_id:
        print(f"❌ 未获取到product_id")
        save_task_status(
            keer_product_id=keer_product_id,
            sp_status="未获取到product_id",
            quotation_feedback_status=2
        )
        return False

    print(f"✅ 获取到product_id: {product_id}")
    print(f"   Supplier Name (from Keer): {supplier_name_from_keer}")

    # 4. 获取产品详细报价信息
    print(f"\n📋 获取产品详细信息...")
    detail_result = get_product_quotation(SP_API_KEY, product_id, is_attachment_needed=1)

    if not detail_result or not detail_result.get('success'):
        print(f"❌ 获取产品详情失败: {detail_result}")
        save_task_status(
            keer_product_id=keer_product_id,
            sp_status="获取产品详情失败",
            quotation_feedback_status=2
        )
        return False

    detail_data = detail_result.get('data', [])
    if not detail_data:
        print(f"❌ 产品详情为空")
        save_task_status(
            keer_product_id=keer_product_id,
            sp_status="产品详情为空",
            quotation_feedback_status=2
        )
        return False

    product_detail = detail_data[0]
    shopify_product_id = product_detail.get('product_shopify_id')
    quotation_information = product_detail.get('quotation_information', {})

    # 提取supplier_name用于对比
    supplier_detail = product_detail.get('supplier_detail', {})
    supplier_name_from_sp = supplier_detail.get('supplier_name', '') if isinstance(supplier_detail, dict) else ''

    print(f"✅ 获取到产品详情")
    print(f"   Product ID: {product_id}")
    print(f"   Shopify ID: {shopify_product_id}")
    print(f"   Supplier Name (from SP): {supplier_name_from_sp}")

    # 5. 对比supplier_name（大小写敏感）
    name_mismatch = False
    special_sp_status = None

    if supplier_name_from_keer and supplier_name_from_sp:
        if supplier_name_from_keer != supplier_name_from_sp:
            name_mismatch = True
            special_sp_status = f"当前产品在{supplier_name_from_keer}账号，现在在{supplier_name_from_sp}账号"
            print(f"\n⚠️  检测到supplier_name不一致:")
            print(f"   Keer接口返回: {supplier_name_from_keer}")
            print(f"   SP详情返回: {supplier_name_from_sp}")
            print(f"   将在最后回传特殊sp_status: {special_sp_status}")
        else:
            print(f"\n✅ Supplier name一致: {supplier_name_from_sp}")
    else:
        print(f"\n⚠️  Supplier name未完全获取到，跳过对比")

    # 6. 提取国家代码映射和variant信息
    country_mapping = get_country_id_mapping(quotation_information)
    print(f"\n🌍 国家映射: {country_mapping}")

    country_variants = {}
    for country_code, variants in quotation_information.items():
        if variants:
            country_variants[country_code] = variants
            print(f"   {country_code}: {len(variants)} 个变体")

    if not country_variants:
        print(f"❌ 错误: 未找到产品变体信息")
        save_task_status(
            keer_product_id=keer_product_id,
            quotation_feedback_status=2
        )
        return False

    # ==================== 检测并准备删除缺失的国家 ====================
    print(f"\n🔍 检查国家报价完整性...")

    # 从报价数据中获取所有有报价的国家
    countries_with_quotes = set()
    for quote in quotation_result:
        original_nation = quote.get('nation')
        if original_nation and quote.get('price', 0) > 0:  # ✅ 只统计价格>0的国家
            normalized_nation = normalize_country_code(original_nation)
            countries_with_quotes.add(normalized_nation)

    print(f"   📊 Service Points产品包含国家: {set(country_variants.keys())}")
    print(f"   📊 报价数据包含国家: {countries_with_quotes}")

    # 找出缺失的国家
    all_countries_in_sp = set(country_variants.keys())
    missing_countries = all_countries_in_sp - countries_with_quotes

    # 准备delete_variant参数
    delete_variant_data = {}

    if missing_countries:
        print(f"\n⚠️  检测到缺失国家: {missing_countries}")
        print(f"   将在提交报价时同时删除这些国家的变体")

        # 按国家收集variant_id
        for missing_country in missing_countries:
            country_id = country_mapping.get(missing_country)
            if not country_id:
                continue

            variants = country_variants.get(missing_country, [])
            variant_ids = []

            print(f"\n   📋 国家 {missing_country} (country_id: {country_id}) 的变体:")
            for idx, variant in enumerate(variants, 1):
                variant_id = variant.get('variant_id')
                if variant_id:
                    variant_ids.append(variant_id)
                    if idx <= 5:  # 只显示前5个
                        print(f"      - variant_id: {variant_id}")

            if len(variants) > 5:
                print(f"      ... 还有 {len(variants) - 5} 个变体")

            # 添加到delete_variant_data
            if variant_ids:
                delete_variant_data[str(country_id)] = variant_ids

        print(f"\n   📊 delete_variant 参数:")
        print(f"      {json.dumps(delete_variant_data, ensure_ascii=False)}")
    else:
        print(f"✅ 所有国家都有报价数据，无需删除变体")

    # ==================== 构建报价参数 ====================

    # 7. 构建报价参数
    print(f"\n💰 开始构建报价参数...")

    quotation_payload = {
        "product_id": int(product_id),
        "shopify_product_id": int(shopify_product_id),
        "is_quotation_product": 2,
        "is_new_price_submitted": 0,
        "expected_processing_time": "3-5 days",
        "expecting_shipping_time": "7-9 days",
        "product_quality": "3",
        "start_fulfillment_delay": "0 day",
        "reason_fulfillment_delay": ""
    }

    # ✅ 添加delete_variant参数（如果有缺失国家）
    if delete_variant_data:
        quotation_payload["delete_variant"] = delete_variant_data
        print(f"   ✅ 已添加 delete_variant 参数")

    price_params_count = 0
    skipped_zero_price = 0
    skipped_no_country = 0
    country_code_conversions = {}

    for quote in quotation_result:
        original_nation = quote.get('nation')
        quantity = quote.get('quantity')
        price = quote.get('price')

        if not original_nation or quantity is None or price is None:
            continue

        if price == 0:
            skipped_zero_price += 1
            continue

        nation = normalize_country_code(original_nation)

        if original_nation != nation:
            if original_nation not in country_code_conversions:
                country_code_conversions[original_nation] = nation

        country_id = country_mapping.get(nation)
        variants = country_variants.get(nation)

        if not country_id or not variants:
            skipped_no_country += 1
            continue

        for variant in variants:
            variant_id = variant.get('variant_id')
            if not variant_id:
                continue

            calculated_price = round(price * 0.99, 2)
            param_name = f"pcs_{quantity}_{variant_id}_{country_id}"
            quotation_payload[param_name] = str(calculated_price)

            price_params_count += 1
            if price_params_count <= 15:
                print(f"   ✅ {param_name} = {calculated_price} (原价: {price})")

    if price_params_count > 15:
        print(f"   ... 还有 {price_params_count - 15} 个价格参数未显示")

    if country_code_conversions:
        print(f"\n   ℹ️  国家代码转换:")
        for original, converted in country_code_conversions.items():
            print(f"      {original} -> {converted}")

    if skipped_zero_price > 0:
        print(f"\n   ⚠️  跳过价格为0的报价: {skipped_zero_price} 条")
    if skipped_no_country > 0:
        print(f"   ⚠️  跳过未找到country_id的报价: {skipped_no_country} 条")

    if price_params_count == 0:
        print(f"\n❌ 错误: 未能生成任何价格参数")
        save_task_status(
            keer_product_id=keer_product_id,
            quotation_feedback_status=2
        )
        return False

    print(f"\n📤 报价参数构建完成，共 {price_params_count} 个有效价格")

    # 8. 提交报价（包含delete_variant）
    print(f"\n🚀 正在提交报价...")
    if delete_variant_data:
        print(f"   ℹ️  同时删除 {len(delete_variant_data)} 个国家的变体")

    update_result = update_product_quotation(SP_API_KEY, quotation_payload)

    if not update_result or not update_result.get('success'):
        print(f"\n❌ 报价提交失败!")
        print(f"响应: {update_result}")
        save_task_status(
            keer_product_id=keer_product_id,
            quotation_feedback_status=2
        )
        return False

    print(f"\n✅✅✅ 报价提交成功! ✅✅✅")
    print(f"响应: {update_result.get('data')}")

    if delete_variant_data:
        print(f"✅ 缺失国家的变体已成功删除!")

    # ==================== 报价成功，继续处理消息和图片 ====================

    # 9. 重新获取产品详情以获得quotation_id
    print(f"\n📋 重新获取产品详情以获得quotation_id...")
    detail_result_2 = get_product_quotation(SP_API_KEY, product_id, is_attachment_needed=1)

    if not detail_result_2 or not detail_result_2.get('success'):
        print(f"❌ 重新获取产品详情失败")
        save_task_status(
            keer_product_id=keer_product_id,
            quotation_feedback_status=3
        )
        return False

    product_detail_2 = detail_result_2.get('data', [])[0]
    quotation_id = product_detail_2.get('quotation_id')
    client_account_id = product_detail_2.get('client_account_id')
    client_user_id = product_detail_2.get('client_user_id')
    quotation_request_id = product_detail_2.get('quotation_request_id')

    print(f"✅ 获取到quotation_id: {quotation_id}")
    print(f"   client_account_id: {client_account_id}")
    print(f"   client_user_id: {client_user_id}")
    print(f"   quotation_request_id: {quotation_request_id}")

    # 10. 获取消息内容
    print(f"\n📝 获取消息内容...")
    message_content = get_message_content(keer_product_id)
    print(f"   消息内容: {message_content[:100]}...")

    # 11. 获取待上传图片
    print(f"\n📸 获取待上传图片...")
    old_images_str = get_uploaded_images(keer_product_id)
    all_images_str = get_all_product_images(keer_product_id)

    print(f"   已上传图片: {old_images_str[:100] if old_images_str else '无'}")
    print(f"   所有实拍图: {all_images_str[:150] if all_images_str else '无'}")

    new_images_list = calculate_new_images(all_images_str, old_images_str)

    if new_images_list:
        print(f"   ✅ 找到 {len(new_images_list)} 张待上传图片")
    else:
        print(f"   ℹ️  没有新图片需要上传")

    # 12. 下载并编码图片
    image_files = []
    successfully_downloaded_images = []
    failed_images = []

    if new_images_list:
        print(f"\n📥 开始下载图片...")
        for i, img_url in enumerate(new_images_list, 1):
            encoded_image = download_and_encode_image(img_url, i)
            if encoded_image:
                image_files.append(encoded_image)
                successfully_downloaded_images.append(img_url)
            else:
                failed_images.append(img_url)
                print(f"      ⚠️  图片 {i} 处理失败，跳过该图片")

        # 统计结果
        print(f"\n   📊 图片处理结果:")
        print(f"      ✅ 成功: {len(successfully_downloaded_images)}/{len(new_images_list)} 张")
        if failed_images:
            print(f"      ❌ 失败: {len(failed_images)} 张")
            for failed_url in failed_images:
                print(f"         - {failed_url[:80]}...")

        # 只有所有图片都失败才整体失败
        if len(image_files) == 0 and len(new_images_list) > 0:
            print(f"\n      ❌ 所有图片处理失败 - 整体失败")
            save_task_status(
                keer_product_id=keer_product_id,
                quotation_feedback_status=3
            )
            return False

    # 13. 发送消息和图片
    print(f"\n📤 发送消息和图片到Service Points...")

    if image_files:
        print(f"   准备发送 {len(image_files)} 张图片")

    message_data = {
        'product_id': int(product_id),
        'shopify_product_id': int(shopify_product_id),
        'quotation_id': int(quotation_id) if quotation_id else 0,
        'client_account_id': int(client_account_id) if client_account_id else 0,
        'client_user_id': int(client_user_id) if client_user_id else 0,
        'quotation_request_id': int(quotation_request_id) if quotation_request_id else 0,
        'description': message_content
    }

    send_result = send_product_message(SP_API_KEY, message_data, image_files if image_files else None)

    if not send_result or not send_result.get('success'):
        print(f"❌ 发送消息失败: {send_result}")
        print(f"⚠️  不更新shi_image_note")
        save_task_status(
            keer_product_id=keer_product_id,
            quotation_feedback_status=3
        )
        return False

    print(f"✅ 消息和图片发送成功!")

    # 14. 更新已上传图片记录
    if successfully_downloaded_images:
        print(f"\n📝 更新已上传图片记录...")

        new_images_str = ','.join(successfully_downloaded_images)
        if old_images_str:
            updated_shi_image_note = old_images_str + ',' + new_images_str
        else:
            updated_shi_image_note = new_images_str

        print(f"   新上传: {len(successfully_downloaded_images)} 张")
        print(f"   总计: {len(updated_shi_image_note.split(','))} 张")

        update_success = save_task_status(
            keer_product_id=keer_product_id,
            shi_image_note=updated_shi_image_note
        )

        if update_success:
            print(f"✅ 图片记录更新成功")
        else:
            print(f"❌ 图片记录更新失败")

    # 15. 最终成功
    print(f"\n📝 保存最终成功状态...")
    # 如果name不一致，额外保存特殊sp_status
    if name_mismatch and special_sp_status:
        print(f"   ⚠️  同时保存特殊sp_status: {special_sp_status}")
        save_task_status(
            keer_product_id=keer_product_id,
            quotation_feedback_status=1,
            sp_status=special_sp_status
        )
    else:
        save_task_status(
            keer_product_id=keer_product_id,
            quotation_feedback_status=1
        )

    # ✅ 16. 调用update_sp_status接口
    update_sp_status(keer_product_id)

    print(f"\n🎉🎉🎉 任务处理完成! (quotation_feedback_status=1) 🎉🎉🎉")
    return True


# ==================== 主程序 ====================

def main():
    """
    主程序入口 - 依次处理今天、昨天、前天的任务
    处理顺序：今天全部任务 → 昨天全部任务 → 前天全部任务

    返回值：
    - True: 有任务被处理
    - False: 没有任务
    """
    print("=" * 100)
    print("Service Points 自动报价系统")
    print("=" * 100)

    store_code = "SP00001"

    # 获取需要处理的日期列表
    date_list = get_date_list()

    print(f"\n📅 处理顺序:")
    print(f"   1. {date_list[0]} (今天)")
    print(f"   2. {date_list[1]} (昨天)")
    print(f"   3. {date_list[2]} (前天)")

    # 统计总体结果
    total_success = 0
    total_fail = 0
    total_tasks = 0

    # 遍历每个日期
    for date_index, created_at in enumerate(date_list, 1):
        date_name = ["今天", "昨天", "前天"][date_index - 1]

        print(f"\n\n{'#' * 100}")
        print(f"开始处理 {date_name} ({created_at}) 的任务")
        print(f"{'#' * 100}")

        # 1. 获取两种任务
        print("\n📥 获取待处理任务...")

        # 获取报价任务
        print("\n📋 获取报价任务...")
        quotation_tasks_result = get_internal_tasks(store_code, created_at)
        quotation_tasks = parse_task_data(quotation_tasks_result)
        print(f"✅ 获取到 {len(quotation_tasks)} 个报价任务")

        # 获取标记不可报价任务
        print("\n📋 获取标记不可报价任务...")
        non_quotable_tasks_result = get_non_quotable_tasks(store_code, created_at)
        non_quotable_tasks = parse_task_data(non_quotable_tasks_result)
        print(f"✅ 获取到 {len(non_quotable_tasks)} 个标记不可报价任务")

        # 统计当前日期任务数
        date_total_tasks = len(quotation_tasks) + len(non_quotable_tasks)
        total_tasks += date_total_tasks

        if date_total_tasks == 0:
            print(f"\n⚠️  {date_name} ({created_at}) 没有待处理的任务，跳过")
            continue

        print(f"\n📊 {date_name} 任务统计:")
        print(f"   报价任务: {len(quotation_tasks)} 个")
        print(f"   标记不可报价任务: {len(non_quotable_tasks)} 个")
        print(f"   总计: {date_total_tasks} 个")

        # 2. 处理任务
        date_success_count = 0
        date_fail_count = 0
        task_index = 0

        # 先处理报价任务
        for i, task in enumerate(quotation_tasks, 1):
            task_index += 1
            print(f"\n\n{'=' * 100}")
            print(
                f"[{date_name} {created_at}] 处理任务 {task_index}/{date_total_tasks} - 报价任务 {i}/{len(quotation_tasks)}")
            print(f"{'=' * 100}")

            result = process_quotation_task(task)

            if result:
                date_success_count += 1
                total_success += 1
            else:
                date_fail_count += 1
                total_fail += 1

            # 避免请求过快，添加延迟
            if task_index < date_total_tasks:
                print(f"\n⏳ 等待3秒后处理下一个任务...")
                time.sleep(3)

        # 再处理标记不可报价任务
        for i, task in enumerate(non_quotable_tasks, 1):
            task_index += 1
            print(f"\n\n{'=' * 100}")
            print(
                f"[{date_name} {created_at}] 处理任务 {task_index}/{date_total_tasks} - 标记不可报价任务 {i}/{len(non_quotable_tasks)}")
            print(f"{'=' * 100}")

            result = process_non_quotable_task(task)

            if result:
                date_success_count += 1
                total_success += 1
            else:
                date_fail_count += 1
                total_fail += 1

            # 避免请求过快，添加延迟
            if task_index < date_total_tasks:
                print(f"\n⏳ 等待3秒后处理下一个任务...")
                time.sleep(3)

        # 3. 输出当前日期统计结果
        print(f"\n\n{'=' * 100}")
        print(f"{date_name} ({created_at}) 处理完成 - 统计结果")
        print(f"{'=' * 100}")
        print(f"总任务数: {date_total_tasks}")
        print(f"   报价任务: {len(quotation_tasks)}")
        print(f"   标记不可报价任务: {len(non_quotable_tasks)}")
        print(f"✅ 成功: {date_success_count}")
        print(f"❌ 失败: {date_fail_count}")
        if date_total_tasks > 0:
            print(f"成功率: {date_success_count / date_total_tasks * 100:.1f}%")
        print(f"{'=' * 100}")

    # 4. 输出总体统计结果
    print(f"\n\n{'#' * 100}")
    print("所有日期处理完成 - 总体统计")
    print(f"{'#' * 100}")
    print(f"处理日期:")
    print(f"   1. {date_list[0]} (今天)")
    print(f"   2. {date_list[1]} (昨天)")
    print(f"   3. {date_list[2]} (前天)")
    print(f"\n总任务数: {total_tasks}")
    print(f"✅ 总成功: {total_success}")
    print(f"❌ 总失败: {total_fail}")
    if total_tasks > 0:
        print(f"总成功率: {total_success / total_tasks * 100:.1f}%")
    print(f"{'#' * 100}")

    # 返回是否有任务被处理
    return total_tasks > 0


def run_loop():
    """
    无限循环执行主程序

    执行逻辑：
    1. 完成今天的所有任务（报价任务 + 不可报价标记任务）
    2. 完成昨天的所有任务（报价任务 + 不可报价标记任务）
    3. 完成前天的所有任务（报价任务 + 不可报价标记任务）
    4. 如果有任务被处理，立即开始下一轮
    5. 如果没有任务，等待30秒后再开始下一轮
    """
    loop_count = 0

    print("\n" + "🔄" * 50)
    print("启动无限循环模式")
    print(f"执行顺序: 今天全部任务 → 昨天全部任务 → 前天全部任务")
    print(f"有任务: 立即开始下一轮 | 无任务: 等待{LOOP_INTERVAL}秒")
    print("按 Ctrl+C 停止程序")
    print("🔄" * 50 + "\n")

    while True:
        try:
            loop_count += 1
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            print(f"\n\n{'🔄' * 50}")
            print(f"第 {loop_count} 轮循环开始")
            print(f"当前时间: {current_time}")
            print(f"{'🔄' * 50}\n")

            # 执行主程序（会依次处理今天、昨天、前天）
            has_tasks = main()

            # 根据是否有任务决定等待策略
            if has_tasks:
                # 有任务 - 立即开始下一轮
                print(f"\n\n{'⚡' * 50}")
                print(f"第 {loop_count} 轮循环完成")
                print(f"✅ 有任务被处理，立即开始下一轮")
                print(f"{'⚡' * 50}\n")
                # 不等待，直接继续下一轮
            else:
                # 没有任务 - 等待30秒
                next_time = (datetime.now() + timedelta(seconds=LOOP_INTERVAL)).strftime("%Y-%m-%d %H:%M:%S")
                print(f"\n\n{'⏰' * 50}")
                print(f"第 {loop_count} 轮循环完成")
                print(f"ℹ️  没有任务需要处理，等待 {LOOP_INTERVAL} 秒")
                print(f"下一轮开始时间: {next_time}")
                print(f"{'⏰' * 50}\n")
                time.sleep(LOOP_INTERVAL)

        except KeyboardInterrupt:
            print(f"\n\n{'🛑' * 50}")
            print("接收到停止信号")
            print(f"程序已运行 {loop_count} 轮循环")
            print("程序已安全退出")
            print(f"{'🛑' * 50}\n")
            break
        except Exception as e:
            print(f"\n\n{'❌' * 50}")
            print(f"第 {loop_count} 轮循环发生错误: {e}")
            print("5秒后继续下一轮...")
            print(f"{'❌' * 50}\n")
            time.sleep(5)


if __name__ == "__main__":
    # 启动无限循环
    run_loop()