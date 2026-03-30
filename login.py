import time
import random
import os
from datetime import datetime

def execute_login(page, target_url, username, password):
    def get_time(): return time.strftime('%H:%M:%S')
    
    try:
        yield f"[{get_time()}] 正在访问: {target_url}"
        page.goto(target_url, wait_until="commit", timeout=15000)
        
        if username and password:
            yield f"[{get_time()}] 正在扫描页面认证组件..."
            time.sleep(2) 
            
            user_field = page.locator("input[placeholder*='一卡通'], input[placeholder*='ID'], .input-username-pc").first
            pwd_field = page.locator("input[type='password'], input[placeholder*='密码']").first
            login_btn = page.locator("button:has-text('登 录'), .login-button-pc, .ant-btn-primary").first

            user_field.wait_for(state="visible", timeout=10000)
            user_field.click()
            user_field.fill("")
            user_field.type(username, delay=random.randint(50,100))
            
            pwd_field.click()
            pwd_field.type(password, delay=random.randint(50,150))
            
            yield f"[{get_time()}] 凭据录入成功，准备提交..."
            login_btn.click()
            
            page.wait_for_url(lambda url: "authserver" not in url.lower() and "login" not in url.lower(), timeout=60000)
            yield f"[{get_time()}] 成功：页面已完成认证跳转。"
            
    except Exception as e:
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = f"error_screenshot_{timestamp}.png"
        try:
           
            page.screenshot(path=screenshot_path, full_page=True)
            yield f"[{get_time()}] [排障] 已保存崩溃现场截图至根目录: {screenshot_path}"
        except Exception as ss_e:
            yield f"[{get_time()}] 截图生成失败: {str(ss_e)}"
            
        yield f"[{get_time()}] 登录引擎崩溃: {str(e)}"
        raise e  


   