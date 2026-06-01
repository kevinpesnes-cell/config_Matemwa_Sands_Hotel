import time
import os
import sys
import shutil
import subprocess
import json
import base64
import itertools
import requests
import argparse
import msvcrt  # للقفل على ويندوز لمنع تشغيل نسخ متعددة

# --- دالات التشفير (مستنسخة لضمان الاستقلالية) ---
def get_internal_key() -> str:
    key = os.getenv("INTERNAL_KEY")
    if key:
        return key
    return "InfinitySmart_Secret_2026"

def simple_decrypt(encoded_data, key=None):
    if key is None:
        key = get_internal_key()
    try:
        if isinstance(encoded_data, str):
            encoded_data = encoded_data.encode("utf-8")
        data = base64.b64decode(encoded_data)
        key_bytes = key.encode("utf-8")
        xored = bytes(a ^ b for a, b in zip(data, itertools.cycle(key_bytes)))
        return xored.decode("utf-8")
    except Exception:
        return None

def simple_crypt(data, key=None):
    if key is None:
        key = get_internal_key()
    if isinstance(data, str):
        data = data.encode('utf-8')
    key_bytes = key.encode('utf-8')
    xored = bytes(a ^ b for a, b in zip(data, itertools.cycle(key_bytes)))
    return base64.b64encode(xored).decode('utf-8')

def is_newer_version(remote, local):
    """مقارنة ذكية لأرقام الإصدارات"""
    try:
        import re
        def parse_v(v):
            return [int(x) for x in re.sub(r'[^0-9.]', '', str(v)).split('.') if x]
        r_parts = parse_v(remote)
        l_parts = parse_v(local)
        max_len = max(len(r_parts), len(l_parts))
        r_parts.extend([0] * (max_len - len(r_parts)))
        l_parts.extend([0] * (max_len - len(l_parts)))
        return r_parts > l_parts
    except:
        return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-config", action="store_true", help="Force pull config from server")
    parser.add_argument("--nuclear-config", action="store_true", help="Replace config.dat with config_new.dat immediately")
    parser.add_argument("--new-version", type=str, help="Update version field in config after EXE replacement")
    args = parser.parse_args()

    # 1. تعريف المسارات بشكل مطلق
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
    os.chdir(base_dir)
    
    new_exe = "InfinitySmart_new.exe"
    old_exe = "InfinitySmart.exe"
    config_dat = "config.dat"
    config_new = "config_new.dat"
    state_file = "last_state.json"
    error_log = "update_error.txt"
    lock_file = "updater.lock"
    
    def log_error(msg):
        ts = time.ctime()
        try:
            with open(error_log, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except: pass
        print(f"[{ts}] {msg}")

    # منع تشغيل أكثر من نسخة من المحدث في نفس الوقت
    lock_f = open(lock_file, 'w')
    try:
        msvcrt.locking(lock_f.fileno(), msvcrt.LK_NBLCK, 1)
    except IOError:
        print("⚠️ Another instance of updater is already running. Exiting.")
        sys.exit(0)

    log_error("🚀 InfinitySmart NUCLEAR Updater Started.")

    # 2. إغلاق البرنامج الرئيسي لضمان تحرير الملفات
    log_error("Closing Agent processes...")
    processes_to_kill = ["InfinitySmart.exe", "main.exe", "InfinitySmart"]
    for proc in processes_to_kill:
        try:
            # استخدام /T لقتل شجرة العمليات بالكامل و /F للإجبار
            subprocess.run(["taskkill", "/F", "/IM", proc, "/T"], 
                           capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        except: pass
    
    # محاولة إضافية للتأكد من انغلاق الملفات (هام جداً للتحديث عن بعد)
    time.sleep(5) 
    for i in range(10):
        try:
            if os.path.exists(old_exe):
                with open(old_exe, "ab") as f:
                    pass # إذا استطعنا فتح الملف للكتابة، فهذا يعني أنه غير مقفل
            log_error("✅ Main EXE is unlocked.")
            break
        except OSError:
            log_error(f"⚠️ Main EXE still locked, waiting... ({i+1}/10)")
            time.sleep(2)
            for proc in processes_to_kill:
                subprocess.run(["taskkill", "/F", "/IM", proc, "/T"], 
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)

    # 3. معالجة تحديث الكونفيج (الخيار النووي)
    if args.nuclear_config:
        if os.path.exists(config_new):
            for i in range(5):
                try:
                    log_error(f"Nuclear Config Mode: Replacing config.dat (Attempt {i+1})...")
                    if os.path.exists(config_dat):
                        try:
                            # إنشاء نسخة احتياطية قبل الحذف
                            backup_path = config_dat + ".bak"
                            shutil.copy2(config_dat, backup_path)
                            log_error(f"📦 Backup created: {backup_path}")
                            os.remove(config_dat)
                        except OSError as e:
                            log_error(f"Could not remove old config: {e}")
                    
                    os.rename(config_new, config_dat)
                    log_error("✅ Config replaced successfully.")
                    
                    # تنظيف ملف الحالة لضمان عدم وجود ماكينات قديمة متداخلة مع الجديدة
                    if os.path.exists(state_file):
                        try:
                            os.remove(state_file)
                            log_error("🧹 Local state file (last_state.json) cleared for a fresh start.")
                        except Exception as se:
                            log_error(f"⚠️ Could not clear state file: {se}")
                    break
                except Exception as e:
                    log_error(f"⚠️ Attempt {i+1} failed: {e}")
                    time.sleep(2)
            else:
                log_error("❌ Failed to replace config after 5 attempts.")
        else:
            # إذا لم يكن هناك ملف جديد، لا داعي لمحاولة الاستبدال (تجنب الخطأ الذي ظهر في اللوج)
            log_error("ℹ️ No 'config_new.dat' found to replace. Skipping nuclear step.")

    # 4. تحميل الإعدادات الحالية
    config = None
    if os.path.exists(config_dat):
        try:
            with open(config_dat, "rb") as f:
                decrypted = simple_decrypt(f.read())
                if decrypted: config = json.loads(decrypted)
        except Exception as e:
            log_error(f"Error reading config: {e}")

    if config:
        updates_cfg = config.get("updates") or config.get("remote_update", {})
        config_url = updates_cfg.get("config_url") or updates_cfg.get("url")
        auth_token = updates_cfg.get("auth_token") or config.get("server", {}).get("auth_token", "")
        headers = {"Authorization": f"Bearer {auth_token}"}
        location = config.get("report", {}).get("location_name", "Unknown")

        # سحب الكونفيج الجديد (فقط في حالة التشغيل اليدوي أو طلب الأجينت)
        is_manual_run = not (args.force_config or args.nuclear_config)
        if args.force_config or is_manual_run:
            if config_url:
                try:
                    final_cfg_url = config_url
                    if not config_url.lower().endswith(".dat"):
                        safe_name = "".join([c if c.isalnum() or c in (' ', '-', '_') else "_" for c in location]).strip().replace(" ", "_").lower()
                        final_cfg_url = f"{config_url.rstrip('/')}/{safe_name}.dat"

                    log_error(f"🔍 Pulling fresh config from: {final_cfg_url}")
                    r_cfg = requests.get(final_cfg_url, params={"location": location, "t": int(time.time())}, headers=headers, timeout=60)
                    
                    if r_cfg.status_code == 200 and len(r_cfg.content) > 100:
                        if not (b"<!DOCTYPE html>" in r_cfg.content[:100] or b"<html" in r_cfg.content[:100]):
                            # فحص الإصدار قبل التحديث
                            remote_config = None
                            try:
                                dec = simple_decrypt(r_cfg.content)
                                if dec: remote_config = json.loads(dec)
                            except: pass

                            if remote_config:
                                remote_ver = remote_config.get("version", "1.0.0")
                                local_ver = config.get("version", "1.0.0")
                                
                                if is_newer_version(remote_ver, local_ver):
                                    for i in range(3):
                                        try:
                                            if os.path.exists(config_dat): os.remove(config_dat)
                                            with open(config_dat, "wb") as f: f.write(r_cfg.content)
                                            log_error(f"✅ Config updated to version {remote_ver}.")
                                            break
                                        except: time.sleep(1)
                                else:
                                    log_error(f"✅ Local config ({local_ver}) is up to date. Server has {remote_ver}.")
                            else:
                                log_error("⚠️ Could not parse remote config for version check.")
                except Exception as e:
                    log_error(f"⚠️ Failed to pull config: {e}")

        # 5. سحب البرنامج الجديد
        app_url = updates_cfg.get("exe_url") or updates_cfg.get("app_url")
        if app_url and not os.path.exists(new_exe):
            try:
                log_error(f"Checking for EXE update...")
                r = requests.get(app_url, headers=headers, timeout=300, stream=True)
                if r.status_code == 200:
                    with open(new_exe, "wb") as f:
                        for chunk in r.iter_content(chunk_size=16384): f.write(chunk)
                    log_error("✅ New EXE downloaded.")
            except Exception as e:
                log_error(f"❌ EXE download failed: {e}")

    # 6. استبدال الـ EXE
    exe_replaced = False
    if os.path.exists(new_exe):
        for i in range(5):
            try:
                log_error(f"Replacing EXE (Attempt {i+1})...")
                if os.path.exists(old_exe): os.remove(old_exe)
                os.rename(new_exe, old_exe)
                log_error("✅ EXE replaced.")
                exe_replaced = True
                break
            except Exception as e:
                log_error(f"⚠️ Attempt {i+1} failed: {e}")
                time.sleep(2)

    # تحديث رقم الإصدار في الكونفيج إذا تم استبدال الـ EXE بنجاح وطلبنا ذلك
    if exe_replaced and args.new_version:
        try:
            log_error(f"Updating config version to {args.new_version}...")
            # إعادة تحميل الكونفيج (قد يكون تغير أثناء التحميل)
            if os.path.exists(config_dat):
                with open(config_dat, "rb") as f:
                    content = f.read()
                
                dec = simple_decrypt(content)
                if dec:
                    cfg_data = json.loads(dec)
                    cfg_data["version"] = args.new_version
                    
                    # حفظ الكونفيج المشفر
                    encrypted = simple_crypt(json.dumps(cfg_data, indent=2, ensure_ascii=False))
                    with open(config_dat, "w", encoding="utf-8") as f:
                        f.write(encrypted)
                    log_error(f"✅ Config version updated to {args.new_version}.")
        except Exception as e:
            log_error(f"⚠️ Failed to update config version: {e}")

    # 7. إعادة تشغيل الأجينت
    if os.path.exists(old_exe):
        log_error("🚀 Restarting InfinitySmart Agent...")
        # إغلاق ملف القفل قبل التشغيل
        lock_f.close()
        try: os.remove(lock_file)
        except: pass
        
        # تشغيل الأجينت بطريقة تضمن استمراره حتى بعد إغلاق المحدث
        try:
            subprocess.Popen([old_exe], 
                             creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS)
            
            # التحقق من أن البرنامج بدأ بالفعل ولم ينهار فوراً
            time.sleep(5)
            log_error("✅ Update process finished. InfinitySmart should be running now.")
        except Exception as e:
            log_error(f"❌ Failed to restart Agent: {e}")
    else:
        log_error("❌ Could not find InfinitySmart.exe to restart!")

if __name__ == "__main__":
    main()
