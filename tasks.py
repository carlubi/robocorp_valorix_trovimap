
import json
import re
from robocorp import browser
from robocorp.tasks import task
from RPA.PDF import PDF
import time
from RPA.Robocorp.Vault import Vault
from robocorp import workitems

@task
def index():
    """
    Main task which solves the RPA challenge!

    Downloads the source data Excel file and uses Playwright to fill the entries inside
    rpachallenge.com.
    """
    browser.configure(
        browser_engine="chromium",
        screenshot="only-on-failure"
    )

    # Get inputs from workitem
    wi = workitems.inputs.current
    raw = wi.payload

    # Si viene como string JSON:
    if isinstance(raw, str):
        payload = json.loads(raw)
    else:
        payload = raw or {}

    catastro_id = payload.get("catastro_id")
    supabase_id = payload.get("supabase_id")

    print("OK:", catastro_id, supabase_id)

    print(f"Catastro ID: {catastro_id}")

    # Get credentials from Vault
    vault = Vault()
    cred = vault.get_secret("valorix")
    email_trovimap = cred["TROVIMAP_EMAIL"]
    password_trovimap = cred["TROVIMAP_PASSWORD"]

    print("Starting automation...")

    try:
        valoracion_url, precio_mercado_estimado = trovimap_valoracion(email_trovimap, password_trovimap, catastro_id)
        
        workitems.outputs.create(
            payload={
                "status": "success",
                "valoracion_url": valoracion_url,
                "precio_mercado_estimado": precio_mercado_estimado,
                "supabase_id": supabase_id
            }
        )
                
        print(f"Valoración URL: {valoracion_url}")
        print(f"Precio Mercado Estimado: {precio_mercado_estimado}")


    except Exception as e:
        print(f"An error occurred: {e}")
        raise e
    finally:
        print("Automation finished!")    
    return precio_mercado_estimado


# Trovimap
def trovimap_valoracion(email, password, catastral):
    """
    Login en Trovimap y lanzamiento de una valoracion de vivienda.
    """
    browser.goto("https://www.trovimap.com/")
    page = browser.page()
    page.wait_for_load_state("domcontentloaded")
    _accept_consent_if_present(page)
    page.wait_for_timeout(1000)

    _click_first(
        page,
        [
            'button:has-text("Entrar")',
            'a:has-text("Entrar")',
            'text=Entrar',
        ],
        "boton Entrar inicial",
    )

    page.wait_for_selector("#user_login_form_email", timeout=15000)
    page.fill("#user_login_form_email", email)
    page.fill("#user_login_form_password", password)

    _click_first(
        page,
        [
            '#new_user_login button:has-text("Entrar")',
            'form button:has-text("Entrar")',
            'button:has-text("Entrar")',
        ],
        "boton Entrar de login",
    )

    page.wait_for_load_state("domcontentloaded", timeout=15000)
    page.wait_for_timeout(2000)

    # Ir directamente a la pagina de valoracion
    browser.goto("https://www.trovimap.com/evaluate/address")
    page.wait_for_load_state("domcontentloaded")
    print(f"URL actual: {page.url}")

    # Esperar a que el formulario Angular se renderice
    try:
        page.wait_for_selector('form[name="evaluateProSearchForm"]', state="visible", timeout=15000)
        print("Formulario evaluateProSearchForm encontrado.")
    except Exception:
        print(f"AVISO: Formulario no encontrado. URL actual: {page.url}")
        print(f"HTML body (primeros 500 chars): {page.locator('body').inner_text()[:500]}")

    page.wait_for_timeout(2000)

    # Rellenar referencia catastral (usar type() para que Angular detecte los eventos)
    input_selectors = [
        'input[placeholder*="Dirección o referencia catastral"]',
        'input[placeholder*="Dirección o referencia catastral"]',
        '#ngb-typeahead-0',
        'trovimap-search-auto-complete input[type="text"]',
        'input.form-control[type="text"]',
    ]
    input_filled = False
    for sel in input_selectors:
        try:
            inp = page.locator(sel).first
            inp.wait_for(state="visible", timeout=5000)
            inp.click()
            inp.fill("")
            inp.type(catastral, delay=50)
            print(f"Catastral escrito en input: {sel}")
            input_filled = True
            break
        except Exception as e:
            print(f"Selector '{sel}' fallo: {e}")
            continue
    if not input_filled:
        raise RuntimeError("No se pudo rellenar el input de catastral.")

    page.wait_for_timeout(1000)

    # Clicar boton "Valorar"
    _click_first(
        page,
        [
            'button[translate="general.beginValuation"]',
            'button:has-text("Valorar")',
            'button.btn-accent[type="submit"]',
        ],
        "boton Valorar",
        timeout=10000,
    )

    page.wait_for_selector("div.modal-body", state="visible", timeout=15000)

    # Paso 8: clicar en la opcion "Piso" (es un div.auto-complete__content, no un boton)
    _click_first(
        page,
        [
            'div.auto-complete__content:has(div.auto-complete__title:has-text("Piso"))',
            'div.auto-complete__title:has-text("Piso")',
            'div.modal-body div:has-text("Piso") >> nth=0',
        ],
        "opcion Piso en modal",
        timeout=10000,
    )

    page.wait_for_timeout(2000)

    # Paso 9: si aparece una lista de pisos, clicar el primero
    try:
        first_item = page.locator(
            'div.modal-body div.auto-complete__content, '
            'div.modal-body div.select-address div.auto-complete__content'
        ).first
        first_item.wait_for(state="visible", timeout=10000)
        first_item.click()
        print("Primer piso de la lista seleccionado.")
    except Exception:
        print("No aparecio lista de pisos, continuando...")

    page.wait_for_timeout(1500)

    # Paso 10: clicar "Valorar" en el footer del modal
    _click_first(
        page,
        [
            'div.modal-footer button[translate="general.value"]',
            'div.modal-footer button.btn-accent',
            'div.modal-footer button:has-text("Valorar")',
            'button[translate="general.value"]',
        ],
        "boton Valorar en modal",
        timeout=10000,
    )

    page.wait_for_load_state("domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
    valoracion_url = page.url
    precio_mercado_estimado = _extract_precio_mercado_estimado(page)

    resultado = {
        "catastral": catastral,
        "valoracion_url": valoracion_url,
        "precio_mercado_estimado": precio_mercado_estimado,
    }
    print(f"Resultado Trovimap: {resultado}")
    return valoracion_url, precio_mercado_estimado

def _click_first(page, selectors, description, timeout=7000):
    last_error = None
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=timeout)
            locator.click()
            return
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"No se pudo clicar {description}. Selectores probados: {selectors}") from last_error

def _extract_precio_mercado_estimado(page):
    body_text = page.locator("body").inner_text()
    patterns = [
        r"Precio de mercado estimado[\s:]*([0-9][0-9\.\,\s]*\s?(?:€|EUR))",
        r"Precio de mercado estimado[\s\S]{0,140}?([0-9][0-9\.\,\s]*\s?(?:€|EUR))",
    ]
    for pattern in patterns:
        match = re.search(pattern, body_text, flags=re.IGNORECASE)
        if match:
            return " ".join(match.group(1).split())

    raise RuntimeError("No se pudo extraer el valor de 'Precio de mercado estimado'.")

def _accept_consent_if_present(page, timeout=15000):
    """
    Cierra el CMP de cookies (Funding Choices) clicando el botón de consentimiento.
    Busca tanto en la pagina principal como en iframes.
    """
    consent_selectors = [
        "button.fc-cta-consent",
        'button[aria-label="Consent"]',
        'button[aria-label="Consentir"]',
        'button:has-text("Consent")',
        'button:has-text("Consentir")',
    ]

    # 1) Intentar directamente en la pagina principal
    for sel in consent_selectors:
        try:
            btn = page.locator(sel).first
            btn.wait_for(state="visible", timeout=1000)
            btn.click(force=True, timeout=2000)
            print(f"Consent clicado en pagina principal: {sel}")
            page.wait_for_timeout(500)
            return
        except Exception:
            continue

    # 2) Buscar en iframes (Google Funding Choices suele estar en un iframe)
    iframe_selectors = [
        'iframe[src*="fundingchoices"]',
        'iframe[src*="consent"]',
        'iframe[src*="googleusercontent"]',
        'iframe[src*="fc.yahoo"]',
        "iframe",  # ultimo recurso: probar todos los iframes
    ]

    deadline = time.time() + (timeout / 1000.0)
    while time.time() < deadline:
        for iframe_sel in iframe_selectors:
            try:
                frame_loc = page.frame_locator(iframe_sel).first
                for sel in consent_selectors:
                    try:
                        btn = frame_loc.locator(sel).first
                        btn.wait_for(state="visible", timeout=1500)
                        btn.click(force=True, timeout=2000)
                        print(f"Consent clicado en iframe ({iframe_sel}): {sel}")
                        page.wait_for_timeout(500)
                        return
                    except Exception:
                        continue
            except Exception:
                continue

        # Tambien probar via page.frames (Playwright Frame objects)
        for frame in page.frames:
            for sel in consent_selectors:
                try:
                    btn = frame.locator(sel).first
                    if btn.is_visible():
                        btn.click(force=True, timeout=2000)
                        print(f"Consent clicado en frame ({frame.url[:60]}): {sel}")
                        page.wait_for_timeout(500)
                        return
                except Exception:
                    continue

        page.wait_for_timeout(500)

    print("No se detecto popup de consent o no se pudo clicar.")
