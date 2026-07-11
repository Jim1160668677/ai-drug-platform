"""运行时冒烟测试 — 验证各功能模块端点正常响应"""
import json
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"
results = []


def call(method, path, token=None, body=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:
        return 0, repr(e)[:200]


def record(module, path, status, note=""):
    ok = 200 <= status < 300
    results.append((module, path, status, ok, note))
    flag = "OK " if ok else "FAIL"
    print(f"[{flag}] {status} {module:10s} {path}  {note}")


print("=== 1. 认证 ===")
st, body = call("POST", "/auth/login", body={"email": "sid@ai-drug.com", "password": "demo123456"})
record("auth", "/auth/login", st)
token = json.loads(body)["access_token"] if st == 200 else None

if token:
    tests = [
        ("projects", "GET", "/projects"),
        ("data", "GET", "/data"),
        ("targets", "GET", "/targets"),
        ("molecules", "GET", "/molecules"),
        ("hypotheses", "GET", "/hypotheses"),
        ("experiments", "GET", "/experiments"),
        ("treatments", "GET", "/treatments"),
        ("reports", "GET", "/reports"),
        ("dashboard", "GET", "/dashboard/overview"),
        ("knowledge", "GET", "/knowledge/genes?q=EGFR"),
        ("audit", "GET", "/audit"),
        ("users", "GET", "/users"),
        ("feedback", "GET", "/feedback"),
        ("efficacy", "GET", "/efficacy"),
        ("workflows", "GET", "/workflows"),
        ("llm-configs", "GET", "/llm-configs"),
        ("federated", "GET", "/federated"),
    ]
    for mod, meth, path in tests:
        st, _ = call(meth, path, token)
        record(mod, path, st)

    print("\n=== AI 问答 (Mock) ===")
    st, body = call("POST", "/chat", token, body={"message": "什么是 EGFR 突变？", "tier": "fast"})
    record("chat", "/chat", st, body[:60] if st == 200 else "")

print("\n" + "=" * 50)
ok = sum(1 for r in results if r[3])
print(f"汇总: {ok}/{len(results)} 通过")
if ok < len(results):
    print("失败项:")
    for m, p, s, _, n in results:
        if not 200 <= s < 300:
            print(f"  - {m} {p} -> {s}  {n}")
