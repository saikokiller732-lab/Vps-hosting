import os, json, time, uuid, shutil, subprocess, threading, signal, secrets, sys, hashlib
from collections import deque
from pathlib import Path
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, request, redirect, url_for, session, render_template, jsonify, Response, send_from_directory, abort, make_response
from werkzeug.utils import secure_filename

APP_DIR = Path(__file__).parent
app = Flask(__name__, template_folder='.')
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

if os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"):
    VOLUME_PATH = Path(os.environ["RAILWAY_VOLUME_MOUNT_PATH"])
    DATA_DIR = VOLUME_PATH / "data"
    FILES_ROOT = VOLUME_PATH / "user_files"
else:
    DATA_DIR = APP_DIR / "data"
    FILES_ROOT = APP_DIR / "user_files"

DATA_DIR.mkdir(parents=True, exist_ok=True)
FILES_ROOT.mkdir(parents=True, exist_ok=True)
USERS_FILE = DATA_DIR / "users.json"
PRICING_FILE = DATA_DIR / "pricing.json"
BOTS_FILE = DATA_DIR / "bots.json"
TRIAL_DEVICES_FILE = DATA_DIR / "trial_devices.json"

OWNER_USER = "HASIB"
OWNER_PASS = "VPS"

DEFAULT_PRICING = {
    "currency": "BDT",
    "contact": "Telegram: @bouchor",
    "admin_name": "Hasib Hossen",
    "admin_telegram": "@bouchor",
    "admin_email": "hasibhossentech@gmail.com",
    "plans": [
        {
            "name": "Free Trial",
            "duration": "24 Hours",
            "price": "0",
            "badge": "FREE",
            "popular": False,
            "ram": "256MB",
            "cpu": "0.5 vCPU",
            "storage": "500MB",
            "bots": 1,
            "python_version": "3.11",
            "features": "1 Python bot, Basic logs, 24h free"
        },
        {
            "name": "Standard",
            "duration": "7 Days",
            "price": "50",
            "badge": "",
            "popular": False,
            "ram": "512MB",
            "cpu": "1 vCPU",
            "storage": "5GB",
            "bots": 3,
            "python_version": "3.11",
            "features": "3 Python bots, Real-time logs, pip install, Auto-restart"
        },
        {
            "name": "Pro",
            "duration": "30 Days",
            "price": "299",
            "badge": "POPULAR",
            "popular": True,
            "ram": "10GB",
            "cpu": "2 vCPU",
            "storage": "50GB",
            "bots": 10,
            "python_version": "3.12",
            "features": "10 Python bots, Priority support, Custom domains, 24/7 uptime"
        },
        {
            "name": "Premium",
            "duration": "Lifetime",
            "price": "499",
            "badge": "BEST VALUE",
            "popular": False,
            "ram": "12GB",
            "cpu": "4 vCPU",
            "storage": "100GB",
            "bots": 999,
            "python_version": "3.12",
            "features": "Unlimited bots, Dedicated help, 24/7 support, All features"
        }
    ]
}

_lock = threading.Lock()

@app.template_filter('timestamp')
def timestamp_filter(ts):
    if not ts:
        return "Never"
    return time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))

def load_users():
    if not USERS_FILE.exists():
        default_users = {}
        save_users(default_users)
        return default_users
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_users(u):
    with _lock:
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(u, f, indent=2, ensure_ascii=False)

def load_pricing():
    if not PRICING_FILE.exists():
        save_pricing(DEFAULT_PRICING)
        return DEFAULT_PRICING
    try:
        with open(PRICING_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return DEFAULT_PRICING

def save_pricing(p):
    with _lock:
        with open(PRICING_FILE, 'w', encoding='utf-8') as f:
            json.dump(p, f, indent=2, ensure_ascii=False)

def load_bots():
    if not BOTS_FILE.exists():
        return {}
    try:
        with open(BOTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_bots(b):
    with _lock:
        with open(BOTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(b, f, indent=2, ensure_ascii=False)

def load_trial_devices():
    if not TRIAL_DEVICES_FILE.exists():
        return {}
    try:
        with open(TRIAL_DEVICES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_trial_devices(td):
    with _lock:
        with open(TRIAL_DEVICES_FILE, 'w', encoding='utf-8') as f:
            json.dump(td, f, indent=2, ensure_ascii=False)

def get_device_fingerprint():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    user_agent = request.headers.get('User-Agent', '')
    accept_lang = request.headers.get('Accept-Language', '')
    accept_encoding = request.headers.get('Accept-Encoding', '')
    device_string = f"{ip}_{user_agent}_{accept_lang}_{accept_encoding}"
    return hashlib.sha256(device_string.encode()).hexdigest()

def get_or_create_trial_user():
    device_id = get_device_fingerprint()
    trial_devices = load_trial_devices()
    
    if device_id in trial_devices:
        trial_username = trial_devices[device_id]
        users = load_users()
        if trial_username in users:
            if time.time() < users[trial_username].get("expires_at", 0):
                return trial_username, False
            else:
                del users[trial_username]
                save_users(users)
                del trial_devices[device_id]
                save_trial_devices(trial_devices)
    
    trial_username = f"trial_{secrets.token_hex(6)}"
    users = load_users()
    users[trial_username] = {
        "password": secrets.token_hex(8),
        "created_at": time.time(),
        "expires_at": time.time() + 24 * 3600,
        "token": secrets.token_urlsafe(16),
        "plan": "Free Trial",
        "is_trial": True
    }
    save_users(users)
    user_dir(trial_username)
    
    trial_devices[device_id] = trial_username
    save_trial_devices(trial_devices)
    
    return trial_username, True

def user_dir(username):
    d = FILES_ROOT / username
    d.mkdir(parents=True, exist_ok=True)
    return d

PROCS = {}
INSTALL_LOGS = {}

def _reader(username, bot_id, proc):
    key = f"{username}_{bot_id}"
    if key not in PROCS:
        return
    buf = PROCS[key]["logs"]
    try:
        for line in iter(proc.stdout.readline, b""):
            try:
                txt = line.decode("utf-8", errors="replace").rstrip()
            except Exception:
                txt = str(line)
            buf.append(f"[{time.strftime('%H:%M:%S')}] {txt}")
    except Exception as e:
        buf.append(f"[reader-error] {e}")
    finally:
        buf.append(f"[exit] process ended with code {proc.poll()}")

def install_requirements(username, bot_dir):
    req_file = bot_dir / "requirements.txt"
    logs = INSTALL_LOGS.setdefault(username, deque(maxlen=1000))
    
    if not req_file.exists():
        logs.append("[install] No requirements.txt found")
        return True
    
    logs.append("[install] Found requirements.txt - Installing packages...")
    
    try:
        with open(req_file, 'r', encoding='utf-8') as f:
            packages = [p.strip() for p in f.read().strip().split('\n') 
                       if p.strip() and not p.startswith('#')]
        
        if not packages:
            logs.append("[install] No packages found in requirements.txt")
            return True
        
        logs.append(f"[install] Installing {len(packages)} packages...")
        
        for pkg in packages:
            logs.append(f"[install] Installing: {pkg}")
            
            try:
                result = subprocess.run(
                    ["pip", "install", pkg, "--upgrade", "--no-cache-dir"],
                    cwd=str(bot_dir),
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                if result.returncode == 0:
                    logs.append(f"[install] {pkg} installed successfully")
                else:
                    error_msg = result.stderr[:150] if result.stderr else "Unknown error"
                    logs.append(f"[install] {pkg} may have issues: {error_msg}")
            except subprocess.TimeoutExpired:
                logs.append(f"[install] {pkg} installation timeout")
            except Exception as e:
                logs.append(f"[install] {pkg} failed: {str(e)[:100]}")
        
        logs.append("[install] Package installation complete!")
        return True
        
    except Exception as e:
        logs.append(f"[install] Error: {str(e)}")
        return False

def get_available_python_versions():
    versions = []
    for v in ['python3.13', 'python3.12', 'python3.11', 'python3.10', 'python3.9', 'python3.8', 'python3']:
        try:
            result = subprocess.run([v, '--version'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                versions.append(v)
        except:
            continue
    return versions

def get_best_python_version():
    available = get_available_python_versions()
    for v in ['python3.12', 'python3.11', 'python3.10', 'python3.9', 'python3.8', 'python3']:
        if v in available:
            return v
    return 'python3'

def detect_bot_type(content):
    content_lower = content.lower()
    if 'telegram' in content_lower or 'updater' in content_lower or 'telegram.bot' in content_lower:
        return 'Telegram Bot'
    elif 'discord' in content_lower or 'discord.client' in content_lower:
        return 'Discord Bot'
    elif 'slack' in content_lower:
        return 'Slack Bot'
    else:
        return 'Python Script'

def start_bot_process(username, bot_id, filename):
    key = f"{username}_{bot_id}"
    stop_bot_process(username, bot_id)
    
    udir = user_dir(username)
    bot_dir = udir / bot_id
    fpath = bot_dir / filename
    
    if key not in PROCS:
        PROCS[key] = {"proc": None, "logs": deque(maxlen=2000), "file": filename, "start_time": None}
    
    logs = PROCS[key]["logs"]
    
    if not fpath.exists():
        return False, "File not found"
    
    ext = fpath.suffix.lower()
    
    if ext == ".py":
        install_requirements(username, bot_dir)
        
        python_cmd = get_best_python_version()
        logs.append(f"[python] Using: {python_cmd}")
        
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                content = f.read()
                bot_type = detect_bot_type(content)
                logs.append(f"[bot] Detected: {bot_type}")
        except:
            logs.append("[bot] Could not detect bot type")
        
        cmd = [python_cmd, "-u", str(fpath)]
        logs.append(f"[start] Starting bot: {filename}")
        
    elif ext in (".js", ".mjs", ".cjs"):
        cmd = ["node", str(fpath)]
        logs.append(f"[start] Starting Node.js: {filename}")
        
    elif ext == ".sh":
        cmd = ["bash", str(fpath)]
        logs.append(f"[start] Starting Bash: {filename}")
        
    else:
        return False, f"Unsupported file type: {ext}"
    
    try:
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONPATH'] = str(bot_dir)
        
        proc = subprocess.Popen(
            cmd, 
            cwd=str(bot_dir), 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT, 
            bufsize=1,
            env=env
        )
    except FileNotFoundError as e:
        return False, f"Runtime not installed: {e}"
    
    PROCS[key]["proc"] = proc
    PROCS[key]["start_time"] = time.time()
    t = threading.Thread(target=_reader, args=(username, bot_id, proc), daemon=True)
    t.start()
    
    logs.append("[start] Bot started successfully!")
    return True, "Bot started successfully"

def stop_bot_process(username, bot_id):
    key = f"{username}_{bot_id}"
    info = PROCS.get(key)
    if not info:
        return False
    p = info.get("proc")
    if p and p.poll() is None:
        try:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        except Exception:
            pass
        info["logs"].append("[stop] Process terminated")
    PROCS[key]["start_time"] = None
    return True

def is_bot_running(username, bot_id):
    key = f"{username}_{bot_id}"
    info = PROCS.get(key)
    if not info:
        return False
    p = info.get("proc")
    return bool(p and p.poll() is None)

def get_bot_start_time(username, bot_id):
    key = f"{username}_{bot_id}"
    info = PROCS.get(key)
    if not info:
        return None
    return info.get("start_time")

def get_bot_runtime(username, bot_id):
    start_time = get_bot_start_time(username, bot_id)
    if not start_time:
        return 0
    if not is_bot_running(username, bot_id):
        return 0
    return int(time.time() - start_time)

def get_bot_logs(username, bot_id):
    key = f"{username}_{bot_id}"
    info = PROCS.get(key)
    if not info:
        return []
    return list(info.get("logs", []))

def delete_bot_process(username, bot_id):
    key = f"{username}_{bot_id}"
    stop_bot_process(username, bot_id)
    if key in PROCS:
        del PROCS[key]
    return True

def get_user_bots(username):
    bots = load_bots()
    return bots.get(username, [])

def get_user_bot_count(username):
    return len(get_user_bots(username))

def get_user_plan(username):
    users = load_users()
    u = users.get(username, {})
    return u.get("plan", "Free Trial")

def get_user_max_bots(username):
    pricing = load_pricing()
    plan_name = get_user_plan(username)
    for p in pricing["plans"]:
        if p["name"] == plan_name:
            return p.get("bots", 1)
    return 1

def can_create_bot(username):
    current = get_user_bot_count(username)
    max_bots = get_user_max_bots(username)
    return current < max_bots

def run_install(username, command, bot_id=None):
    parts = command.strip().split()
    if not parts:
        return False, "Empty command"
    if parts[0] not in ("pip", "pip3", "npm"):
        return False, "Only 'pip install <pkg>' or 'npm install <pkg>' allowed"
    if len(parts) < 3 or parts[1] != "install":
        return False, "Format: pip install <module> OR npm install <module>"
    if any(c in command for c in [";", "&", "|", "`", "$(", ">"]):
        return False, "Invalid characters"
    
    logs = INSTALL_LOGS.setdefault(username, deque(maxlen=1000))
    logs.append(f"[install] $ {command}")
    
    if bot_id:
        cwd = str(user_dir(username) / bot_id)
    else:
        cwd = str(user_dir(username))
    
    def worker():
        try:
            p = subprocess.Popen(parts, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            for line in iter(p.stdout.readline, b""):
                logs.append(line.decode("utf-8", errors="replace").rstrip())
            p.wait()
            logs.append(f"[install] finished with code {p.returncode}")
        except Exception as e:
            logs.append(f"[install-error] {e}")
    
    threading.Thread(target=worker, daemon=True).start()
    return True, "Installing..."

def is_owner():
    return session.get("role") == "owner" and session.get("_owner_valid") == True

def current_user():
    return session.get("username")

def is_trial_user():
    return session.get("is_trial", False)

def user_valid(username):
    users = load_users()
    u = users.get(username)
    if not u:
        return False, "User not found"
    if u.get("expires_at") and time.time() > u["expires_at"]:
        del users[username]
        save_users(users)
        return False, "Account expired"
    return True, u

def require_owner(f):
    @wraps(f)
    def w(*a, **kw):
        if not is_owner():
            return redirect(url_for("login"))
        return f(*a, **kw)
    return w

def require_user(f):
    @wraps(f)
    def w(*a, **kw):
        u = current_user()
        if not u or session.get("role") != "user":
            return redirect(url_for("login"))
        
        if is_trial_user():
            ok, _ = user_valid(u)
            if not ok:
                session.clear()
                return render_template("trial_expired.html")
        else:
            ok, _ = user_valid(u)
            if not ok:
                session.clear()
                return redirect(url_for("login"))
        
        return f(*a, **kw)
    return w

def require_trial_or_user(f):
    @wraps(f)
    def w(*a, **kw):
        u = current_user()
        if not u:
            return redirect(url_for("trial/start"))
        
        if is_trial_user():
            ok, _ = user_valid(u)
            if not ok:
                session.clear()
                return render_template("trial_expired.html")
            return f(*a, **kw)
        
        if session.get("role") == "user":
            ok, _ = user_valid(u)
            if not ok:
                session.clear()
                return redirect(url_for("login"))
            return f(*a, **kw)
        
        return redirect(url_for("login"))
    return w

@app.route("/")
def home():
    if is_owner():
        return redirect(url_for("owner_dashboard"))
    if current_user():
        return redirect(url_for("user_dashboard"))
    return redirect(url_for("landing"))

@app.route("/home")
def landing():
    users = load_users()
    now = time.time()
    return render_template("landing.html", pricing=load_pricing(), users=users, now=now)

@app.route("/pricing")
def pricing_page():
    return render_template("pricing.html", pricing=load_pricing())

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")
        
        if u == OWNER_USER and p == OWNER_PASS:
            session.clear()
            session["role"] = "owner"
            session["username"] = u
            session["_owner_valid"] = True
            session.permanent = True
            return redirect(url_for("owner_dashboard"))
        
        users = load_users()
        info = users.get(u)
        if info and info.get("password") == p:
            ok, msg = user_valid(u)
            if not ok:
                error = msg
            else:
                session.clear()
                session["role"] = "user"
                session["username"] = u
                session["is_trial"] = False
                session.permanent = True
                return redirect(url_for("user_dashboard"))
        else:
            error = "Invalid username or password"
    
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))

@app.route("/auto/<token>")
def auto_login(token):
    users = load_users()
    for uname, info in users.items():
        if info.get("token") == token:
            ok, _ = user_valid(uname)
            if not ok:
                return "Account expired", 403
            session.clear()
            session["role"] = "user"
            session["username"] = uname
            session["is_trial"] = False
            session.permanent = True
            return redirect(url_for("user_dashboard"))
    return "Invalid link", 404

@app.route("/trial/start")
def trial_start():
    trial_username, is_new = get_or_create_trial_user()
    
    session.clear()
    session["role"] = "user"
    session["username"] = trial_username
    session["is_trial"] = True
    session.permanent = True
    
    return redirect(url_for("user_dashboard"))

@app.route("/owner")
@require_owner
def owner_dashboard():
    users = load_users()
    now = time.time()
    changed = False
    for uname in list(users.keys()):
        if users[uname].get("expires_at") and now > users[uname]["expires_at"]:
            del users[uname]
            changed = True
    if changed:
        save_users(users)
    base = request.host_url.rstrip("/")
    trial_devices = load_trial_devices()
    return render_template("owner.html", users=users, now=now, base_url=base, pricing=load_pricing(), trial_devices=trial_devices)

@app.route("/owner/trial/reset")
@require_owner
def reset_trial_limits():
    save_trial_devices({})
    users = load_users()
    for uname in list(users.keys()):
        if uname.startswith("trial_"):
            del users[uname]
            d = FILES_ROOT / uname
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
    save_users(users)
    return jsonify({"ok": True, "msg": "All trial limits and data reset successfully"})

@app.route("/owner/create", methods=["POST"])
@require_owner
def owner_create():
    u = request.form.get("username", "").strip()
    p = request.form.get("password", "").strip()
    plan = request.form.get("plan", "Free Trial").strip()
    try:
        hours = float(request.form.get("hours", "24"))
    except ValueError:
        hours = 24
    if not u or not p:
        return redirect(url_for("owner_dashboard"))
    if u == OWNER_USER:
        return redirect(url_for("owner_dashboard"))
    users = load_users()
    users[u] = {
        "password": p,
        "plan": plan,
        "created_at": time.time(),
        "expires_at": time.time() + hours * 3600 if hours > 0 else 0,
        "token": secrets.token_urlsafe(16),
        "is_free": False
    }
    save_users(users)
    user_dir(u)
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/delete/<username>", methods=["POST"])
@require_owner
def owner_delete(username):
    users = load_users()
    if username in users and username != OWNER_USER:
        del users[username]
        save_users(users)
        d = FILES_ROOT / username
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        bots = load_bots()
        if username in bots:
            del bots[username]
            save_bots(bots)
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/extend/<username>", methods=["POST"])
@require_owner
def owner_extend(username):
    try:
        hours = float(request.form.get("hours", "24"))
    except ValueError:
        hours = 24
    users = load_users()
    if username in users:
        base = max(users[username].get("expires_at") or time.time(), time.time())
        users[username]["expires_at"] = base + hours * 3600
        save_users(users)
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/pricing", methods=["POST"])
@require_owner
def owner_pricing():
    pricing = load_pricing()
    pricing["currency"] = request.form.get("currency", "BDT").strip() or "BDT"
    pricing["contact"] = request.form.get("contact", "").strip()
    pricing["admin_name"] = request.form.get("admin_name", "").strip()
    pricing["admin_telegram"] = request.form.get("admin_telegram", "").strip()
    pricing["admin_email"] = request.form.get("admin_email", "").strip()
    plans = []
    names = request.form.getlist("p_name")
    durs = request.form.getlist("p_duration")
    prices = request.form.getlist("p_price")
    feats = request.form.getlist("p_features")
    badges = request.form.getlist("p_badge")
    populars = request.form.getlist("p_popular")
    rams = request.form.getlist("p_ram")
    cpus = request.form.getlist("p_cpu")
    storages = request.form.getlist("p_storage")
    bot_counts = request.form.getlist("p_bots")
    python_versions = request.form.getlist("p_python_version")
    
    for i in range(len(names)):
        if not names[i].strip():
            continue
        try:
            bot_count = int(bot_counts[i].strip()) if i < len(bot_counts) else 1
        except:
            bot_count = 1
        plans.append({
            "name": names[i].strip(),
            "duration": durs[i].strip() if i < len(durs) else "",
            "price": prices[i].strip() if i < len(prices) else "0",
            "features": feats[i].strip() if i < len(feats) else "",
            "badge": badges[i].strip() if i < len(badges) else "",
            "popular": populars[i] == "on" if i < len(populars) else False,
            "ram": rams[i].strip() if i < len(rams) else "256MB",
            "cpu": cpus[i].strip() if i < len(cpus) else "0.5 vCPU",
            "storage": storages[i].strip() if i < len(storages) else "500MB",
            "bots": bot_count,
            "python_version": python_versions[i].strip() if i < len(python_versions) else "3.11"
        })
    pricing["plans"] = plans
    save_pricing(pricing)
    return redirect(url_for("owner_dashboard") + "#pricing")

@app.route("/dashboard")
@require_trial_or_user
def user_dashboard():
    u = current_user()
    users = load_users()
    info = users.get(u, {})
    
    pricing = load_pricing()
    user_plan = info.get("plan", "Free Trial")
    plan_resources = None
    for p in pricing["plans"]:
        if p["name"] == user_plan:
            plan_resources = p
            break
    
    bots = load_bots()
    user_bots = bots.get(u, [])
    
    return render_template("user.html",
        username=u,
        info=info,
        bots=user_bots,
        plan=plan_resources or pricing["plans"][0],
        expires_at=info.get("expires_at", 0),
        now=time.time(),
        max_bots=get_user_max_bots(u),
        can_create=can_create_bot(u),
        is_trial=info.get("is_trial", False),
        is_free=info.get("is_free", False)
    )

@app.route("/bot/create", methods=["POST"])
@require_trial_or_user
def bot_create():
    u = current_user()
    
    if not can_create_bot(u):
        return jsonify({"ok": False, "msg": "Bot limit reached for your plan"})
    
    bot_id = secrets.token_urlsafe(8)
    bots = load_bots()
    if u not in bots:
        bots[u] = []
    
    bot_dir = user_dir(u) / bot_id
    bot_dir.mkdir(parents=True, exist_ok=True)
    
    bots[u].append({
        "id": bot_id,
        "name": f"Bot {len(bots[u]) + 1}",
        "created_at": time.time(),
        "files": [],
        "status": "stopped",
        "start_time": None
    })
    save_bots(bots)
    
    return jsonify({"ok": True, "bot_id": bot_id})

@app.route("/bot/delete/<bot_id>", methods=["POST"])
@require_trial_or_user
def bot_delete(bot_id):
    u = current_user()
    bots = load_bots()
    
    if u not in bots:
        return jsonify({"ok": False, "msg": "No bots found"})
    
    for i, bot in enumerate(bots[u]):
        if bot["id"] == bot_id:
            delete_bot_process(u, bot_id)
            bot_dir = user_dir(u) / bot_id
            if bot_dir.exists():
                shutil.rmtree(bot_dir, ignore_errors=True)
            bots[u].pop(i)
            save_bots(bots)
            return jsonify({"ok": True})
    
    return jsonify({"ok": False, "msg": "Bot not found"})

@app.route("/bot/upload/<bot_id>", methods=["POST"])
@require_trial_or_user
def bot_upload(bot_id):
    u = current_user()
    bots = load_bots()
    
    if u not in bots:
        return jsonify({"ok": False, "msg": "No bots found"})
    
    bot_found = False
    for bot in bots[u]:
        if bot["id"] == bot_id:
            bot_found = True
            break
    
    if not bot_found:
        return jsonify({"ok": False, "msg": "Bot not found"})
    
    bot_dir = user_dir(u) / bot_id
    files = request.files.getlist("files")
    
    for f in files:
        if not f or not f.filename:
            continue
        name = secure_filename(f.filename)
        if not name:
            continue
        f.save(bot_dir / name)
    
    for bot in bots[u]:
        if bot["id"] == bot_id:
            bot["files"] = [f.name for f in bot_dir.iterdir() if f.is_file()]
            break
    save_bots(bots)
    
    return redirect(url_for("user_dashboard"))

@app.route("/bot/start/<bot_id>", methods=["POST"])
@require_trial_or_user
def bot_start(bot_id):
    u = current_user()
    
    bots = load_bots()
    bot_found = None
    for bot in bots.get(u, []):
        if bot["id"] == bot_id:
            bot_found = bot
            break
    
    if not bot_found:
        return jsonify({"ok": False, "msg": "Bot not found"})
    
    files = bot_found.get("files", [])
    py_files = [f for f in files if f.endswith('.py')]
    
    if not py_files:
        return jsonify({"ok": False, "msg": "No Python file found in bot"})
    
    filename = py_files[0]
    ok, msg = start_bot_process(u, bot_id, filename)
    
    for bot in bots[u]:
        if bot["id"] == bot_id:
            bot["status"] = "running" if ok else "stopped"
            bot["start_time"] = time.time() if ok else None
            break
    save_bots(bots)
    
    return jsonify({"ok": ok, "msg": msg})

@app.route("/bot/stop/<bot_id>", methods=["POST"])
@require_trial_or_user
def bot_stop(bot_id):
    u = current_user()
    stop_bot_process(u, bot_id)
    
    bots = load_bots()
    for bot in bots.get(u, []):
        if bot["id"] == bot_id:
            bot["status"] = "stopped"
            bot["start_time"] = None
            break
    save_bots(bots)
    
    return jsonify({"ok": True})

@app.route("/bot/restart/<bot_id>", methods=["POST"])
@require_trial_or_user
def bot_restart(bot_id):
    u = current_user()
    
    bots = load_bots()
    bot_found = None
    for bot in bots.get(u, []):
        if bot["id"] == bot_id:
            bot_found = bot
            break
    
    if not bot_found:
        return jsonify({"ok": False, "msg": "Bot not found"})
    
    files = bot_found.get("files", [])
    py_files = [f for f in files if f.endswith('.py')]
    
    if not py_files:
        return jsonify({"ok": False, "msg": "No Python file found in bot"})
    
    filename = py_files[0]
    stop_bot_process(u, bot_id)
    time.sleep(0.3)
    ok, msg = start_bot_process(u, bot_id, filename)
    
    for bot in bots[u]:
        if bot["id"] == bot_id:
            bot["status"] = "running" if ok else "stopped"
            bot["start_time"] = time.time() if ok else None
            break
    save_bots(bots)
    
    return jsonify({"ok": ok, "msg": msg})

@app.route("/bot/delete_process/<bot_id>", methods=["POST"])
@require_trial_or_user
def bot_delete_process(bot_id):
    u = current_user()
    delete_bot_process(u, bot_id)
    return jsonify({"ok": True})

@app.route("/bot/logs/<bot_id>")
@require_trial_or_user
def bot_logs(bot_id):
    u = current_user()
    runtime = get_bot_runtime(u, bot_id)
    return jsonify({
        "running": is_bot_running(u, bot_id),
        "logs": get_bot_logs(u, bot_id),
        "install": list(INSTALL_LOGS.get(u, [])),
        "runtime": runtime
    })

@app.route("/logs")
@require_trial_or_user
def logs_api():
    u = current_user()
    return jsonify({
        "running": is_bot_running(u, None) if PROCS.get(u) else False,
        "file": PROCS.get(u, {}).get("file") if PROCS.get(u) else None,
        "logs": get_bot_logs(u, None) if PROCS.get(u) else [],
        "install": list(INSTALL_LOGS.get(u, []))
    })

@app.route("/upload", methods=["POST"])
@require_trial_or_user
def upload():
    u = current_user()
    udir = user_dir(u)
    files = request.files.getlist("files")
    
    for f in files:
        if not f or not f.filename:
            continue
        name = secure_filename(f.filename)
        if not name:
            continue
        f.save(udir / name)
    
    return redirect(url_for("user_dashboard"))

@app.route("/file/delete/<name>", methods=["POST"])
@require_trial_or_user
def file_delete(name):
    u = current_user()
    name = secure_filename(name)
    p = user_dir(u) / name
    if p.exists() and p.is_file():
        p.unlink()
    return redirect(url_for("user_dashboard"))

@app.route("/file/view/<name>")
@require_trial_or_user
def file_view(name):
    u = current_user()
    name = secure_filename(name)
    return send_from_directory(user_dir(u), name, as_attachment=False)

@app.route("/install", methods=["POST"])
@require_trial_or_user
def install():
    u = current_user()
    cmd = request.form.get("command", "").strip()
    bot_id = request.form.get("bot_id", "")
    ok, msg = run_install(u, cmd, bot_id if bot_id else None)
    return jsonify({"ok": ok, "msg": msg})

@app.route("/healthz")
def health():
    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)