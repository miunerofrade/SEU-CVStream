import time
import random
import os
import json
from datetime import datetime

def execute_login(page, target_url, username, password):
    def get_time(): return time.strftime('%H:%M:%S')
    
    try:
        context = page.context
        
        cookie_file = "cookies.json"
        
        if os.path.exists(cookie_file):
            try:
                with open(cookie_file, 'r', encoding='utf-8') as f:
                    cookies = json.load(f)
                    context.add_cookies(cookies)
                yield f"[{get_time()}] 已载入历史 Cookie..."
            except Exception as e:
                yield f"[{get_time()}] 载入 Cookie 失败: {e}"

        yield f"[{get_time()}] 正在访问: {target_url}"
        page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
        
        page.wait_for_timeout(3000) 
        
        current_url = page.url.lower()
        if "auth" not in current_url and "login" not in current_url and "cas" not in current_url:
            yield f"[{get_time()}] 凭据有效，成功跳过登录！"
        else:
            if os.path.exists(cookie_file):
                try:
                    os.remove(cookie_file)
                except:
                    pass
                yield f"[{get_time()}] 历史 Cookie 已失效，将重新登录..."
            
            if username and password:
                yield f"[{get_time()}] 正在扫描页面认证组件..."
                
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
        
        try:
            fresh_cookies = context.cookies()
            with open(cookie_file, 'w', encoding='utf-8') as f:
                json.dump(fresh_cookies, f)
            yield f"[{get_time()}] 最新会话凭证 (Cookies) 已保存。"
        except Exception as e:
            yield f"[{get_time()}] 保存 Cookies 失败: {e}"
            
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


   