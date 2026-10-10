"""Stage 09 end-to-end through a real browser (headless Chromium), screenshots as evidence.

  docker run --rm --network host --shm-size=1g -v "$PWD:/w:z" -w /w --entrypoint python \
      wandersync-ingestion scripts/ui_e2e.py evidence/stage-09 <admin-email> <admin-password>
"""
import json
import sys
import time
import uuid

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

OUT, ADMIN, ADMIN_PW = sys.argv[1], sys.argv[2], sys.argv[3]
APP = "http://localhost:3000"
failures = 0


def check(label, cond, detail=""):
    global failures
    failures += not cond
    print(f"  [{'PASS' if cond else 'FAIL'}] {label} {detail}", flush=True)


o = Options()
for a in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--window-size=1400,1000", "--lang=es-CO"):
    o.add_argument(a)
o.binary_location = "/usr/bin/chromium"
o.set_capability("goog:loggingPrefs", {"performance": "ALL"})
d = webdriver.Chrome(service=Service("/usr/bin/chromedriver"), options=o)
wait = WebDriverWait(d, 60)


def shot(name):
    d.save_screenshot(f"{OUT}/{name}.png")


def text_appears(t, timeout=90):
    WebDriverWait(d, timeout).until(lambda drv: t in drv.find_element(By.TAG_NAME, "body").text)


def login(email, pw, register=False):
    d.get(f"{APP}/ingresar")
    wait.until(EC.presence_of_element_located((By.ID, "email")))
    if register:
        d.find_element(By.XPATH, "//button[contains(., 'Regístrate')]").click()
    d.find_element(By.ID, "email").send_keys(email)
    d.find_element(By.ID, "password").send_keys(pw)
    d.find_element(By.CSS_SELECTOR, "form button[type=submit]").click()
    text_appears("Cerrar sesión", 30)


def search_and_book(fail_at=None):
    d.get(APP)
    wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Buscar')]"))).click()
    text_appears("Tu paquete")
    text_appears("Total")
    time.sleep(1)
    if fail_at:
        Select(d.find_element(By.ID, "failAt")).select_by_value(fail_at)
    shot(f"search-{(fail_at or 'happy').lower()}")
    wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Reservar paquete')]"))).click()
    wait.until(EC.url_contains("/reservas/"))


print("## AC-09.2 happy path from the UI (new traveler registers, searches, books)")
login(f"viajero-{uuid.uuid4().hex[:6]}@test.co", "Viajero-Seguro-2026", register=True)
shot("01-registered")
search_and_book()
text_appears("Reserva ", 10)
time.sleep(3)
shot("02-tracker-running")
text_appears("¡Listo!")
shot("03-tracker-confirmed")
body = d.find_element(By.TAG_NAME, "body").text
check("tracker ends 'Confirmada' with all 4 steps OK", "¡Listo! Vuelo, hotel y auto confirmados." in body, f"(url {d.current_url})")

print("## AC-09.3 car failure from the UI (admin chaos) shows compensations live")
d.find_element(By.XPATH, "//button[contains(., 'Cerrar sesión')]").click()
text_appears("Ingresar", 20)
login(ADMIN, ADMIN_PW)
search_and_book("CAR")
text_appears("Compensaciones (orden inverso)")
shot("04-tracker-compensating")
text_appears("todo fue cancelado y el cobro reembolsado")
shot("05-tracker-cancelled")
body = d.find_element(By.TAG_NAME, "body").text
comp = body.split("Compensaciones (orden inverso)")[1]
order = [comp.index(x) for x in ("Cancelar auto", "Cancelar hotel", "Cancelar vuelo", "Reembolso")]
check("UI shows CANCELLED with Cancelar auto → hotel → vuelo → Reembolso", order == sorted(order))
cancelled_url = d.current_url

print("## AC-09.1 the browser only talks to the backend through /graphql")
calls = set()
for entry in d.get_log("performance"):
    msg = json.loads(entry["message"])["message"]
    if msg["method"] == "Network.requestWillBeSent":
        url = msg["params"]["request"]["url"]
        if not url.startswith(APP) and not url.startswith("data:"):
            calls.add(url.split("?")[0])
print("    non-frontend URLs requested:", sorted(calls))
check("only http://localhost:8000/graphql", calls == {"http://localhost:8000/graphql"})

print("## AC-09.4 errors are shown meaningfully")
d.find_element(By.XPATH, "//button[contains(., 'Cerrar sesión')]").click()
text_appears("Ingresar", 20)
d.get(f"{APP}/ingresar")
wait.until(EC.presence_of_element_located((By.ID, "email"))).send_keys(ADMIN)
d.find_element(By.ID, "password").send_keys("contraseña-incorrecta")
d.find_element(By.CSS_SELECTOR, "form button[type=submit]").click()
text_appears("Correo o contraseña incorrectos.", 20)
shot("06-login-error")
check("wrong password -> 'Correo o contraseña incorrectos.'", True)

print("## AC-09.5 basic accessibility")
d.get(f"{APP}/ingresar")
wait.until(EC.presence_of_element_located((By.ID, "email")))
unlabeled = d.execute_script("""return [...document.querySelectorAll('input,select')].filter(e =>
    e.type !== 'hidden' && !document.querySelector(`label[for="${e.id}"]`) && !e.closest('label')).length""")
d.get(APP)
wait.until(EC.presence_of_element_located((By.ID, "origin")))
unlabeled += d.execute_script("""return [...document.querySelectorAll('input,select')].filter(e =>
    e.type !== 'hidden' && !document.querySelector(`label[for="${e.id}"]`) && !e.closest('label')).length""")
check("every input/select has a label", unlabeled == 0, f"({unlabeled} unlabeled)")
d.find_element(By.TAG_NAME, "body").send_keys("\t\t\t")
focused = d.execute_script("const e=document.activeElement, c=getComputedStyle(e); return [e.tagName, c.outlineStyle, c.outlineWidth]")
check("keyboard focus reaches a control and shows a visible outline", focused[0] != "BODY" and focused[1] != "none" and focused[2] != "0px", f"({focused})")
lang = d.execute_script("return document.documentElement.lang")
check("<html lang='es'>", lang == "es")

print("## Dark mode follows prefers-color-scheme")
light_bg = d.execute_script("return getComputedStyle(document.body).backgroundColor")
d.execute_cdp_cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": "dark"}]})
d.get(APP)
wait.until(EC.presence_of_element_located((By.ID, "origin")))
time.sleep(1)
dark_bg = d.execute_script("return getComputedStyle(document.body).backgroundColor")
shot("07-dark-search")
login(ADMIN, ADMIN_PW)  # the a11y step above left us logged out; orders are owner-only
d.get(cancelled_url)
text_appears("Compensaciones (orden inverso)")
time.sleep(1)
shot("08-dark-tracker")
check("dark token set applies (body background changes)", light_bg != dark_bg, f"(light {light_bg}, dark {dark_bg})")

d.quit()
print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
