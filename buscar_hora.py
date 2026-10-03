"""
Busca la fecha/hora disponible más pronta en agendatuhora.providencia.cl
(Licencia de Conducir > Primera Licencia) y avisa por ntfy.sh.
NO reserva: solo avisa. Reservas tú.

Instalar:  pip install playwright requests && playwright install chromium
Usar:      python buscar_hora.py            # una vez
           python buscar_hora.py --loop 10  # cada 10 min (PC encendido)
           python buscar_hora.py --debug    # navegador visible
"""
import argparse, re, sys, time
import requests
from playwright.sync_api import sync_playwright

URL = "https://agendatuhora.providencia.cl/"
import os
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "fabian-licencia")  # tema de la app ntfy
MESES_A_REVISAR = 3

SUCURSAL = "Municipalidad de Providencia"
CENTRO = "Licencia de Conducir"
SERVICIO_RE = re.compile(r"^Primera Licencia", re.I)


def elegir(page, idx, texto_o_regex):
    """Elige una opción en el select número idx (0,1,2) por texto."""
    sel = page.locator("select").nth(idx)
    sel.wait_for(state="attached", timeout=15000)
    page.wait_for_timeout(800)  # los selects se cargan en cascada
    opciones = sel.locator("option").all_inner_texts()
    for o in opciones:
        o = o.strip()
        ok = texto_o_regex.search(o) if hasattr(texto_o_regex, "search") else o == texto_o_regex
        if ok:
            sel.select_option(label=o)
            return
    raise RuntimeError(f"No encontré la opción {texto_o_regex!r}. Hay: {opciones}")


def buscar(page):
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    elegir(page, 0, SUCURSAL)
    elegir(page, 1, CENTRO)
    elegir(page, 2, SERVICIO_RE)
    page.get_by_text("Siguiente", exact=True).click()
    page.wait_for_url("**/seleccionarCalendario*", timeout=15000)

    page.locator("input").first.click()  # abre el datepicker
    page.wait_for_selector(".ui-datepicker", timeout=10000)

    for _ in range(MESES_A_REVISAR):
        # días habilitados (jQuery UI datepicker)
        dias = page.locator("td[data-handler='selectDay']:not(.ui-state-disabled)")
        if dias.count() > 0:
            primero = dias.first
            mes = primero.get_attribute("data-month")
            anio = primero.get_attribute("data-year")
            dia = primero.inner_text().strip()
            fecha = f"{dia.zfill(2)}-{int(mes) + 1:02d}-{anio}"
            primero.click()
            page.get_by_text("Siguiente", exact=True).click()
            page.wait_for_load_state("networkidle")
            horas = sorted(set(re.findall(r"\b\d{1,2}:\d{2}\b", page.inner_text("body"))))
            return fecha, horas
        page.locator("a[data-handler='next']").click()
        page.wait_for_timeout(500)
    return None, []


def avisar(msg):
    print(msg)
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"),
                      headers={"Title": "Hora disponible en Providencia"}, timeout=10)
    except Exception as e:
        print("No pude enviar aviso:", e)


def una_vez(debug):
    with sync_playwright() as p:
        b = p.chromium.launch(headless=not debug)
        page = b.new_page()
        try:
            fecha, horas = buscar(page)
        finally:
            b.close()
    if fecha:
        actual = f"{fecha} {','.join(horas)}"
        try:
            ultimo = open("ultimo.txt").read()
        except FileNotFoundError:
            ultimo = ""
        if actual != ultimo:
            open("ultimo.txt", "w").write(actual)
            avisar(f"Hora más pronta: {fecha}. Horas: {', '.join(horas) or 'ver sitio'}\n{URL}")
        else:
            print(f"[{time.strftime('%H:%M')}] Sin cambios ({actual}).")
    else:
        print(f"[{time.strftime('%H:%M')}] Sin fechas en los próximos {MESES_A_REVISAR} meses.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, help="minutos entre revisiones")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    while True:
        try:
            una_vez(a.debug)
        except Exception as e:
            print("Error:", e, file=sys.stderr)
        if not a.loop:
            break
        time.sleep(a.loop * 60)
