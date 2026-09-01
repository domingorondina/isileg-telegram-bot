"""
Cliente de Integración con el Sistema de Información de Normativa (SIN)
Poder Ejecutivo de la Provincia de Santa Fe & Boletín Oficial Provincial
https://www.santafe.gov.ar/normativa/ | https://www.santafe.gov.ar/boletinoficial/
"""

import httpx
from bs4 import BeautifulSoup
import urllib.parse
import re
import datetime
from typing import Optional, Dict, Any, List

SIN_BASE_URL = "https://www.santafe.gov.ar/normativa"
BOLETIN_BASE_URL = "https://www.santafe.gov.ar/boletinoficial"
DEFAULT_TIMEOUT = 12.0

class SantaFeSINAPI:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{SIN_BASE_URL}/index.php",
            "Origin": "https://www.santafe.gov.ar"
        }

    def build_boletin_pdf_url(self, fecha_str: str) -> Optional[str]:
        """
        Genera la URL directa del PDF del Boletín Oficial de Santa Fe dada una fecha DD/MM/AAAA o DD-MM-AAAA.
        """
        if not fecha_str:
            return None
        parts = re.split(r"[/-\.]", fecha_str.strip())
        if len(parts) == 3:
            dia, mes, anio = parts[0].zfill(2), parts[1].zfill(2), parts[2]
            if len(anio) == 2:
                anio = f"20{anio}"
            return f"{BOLETIN_BASE_URL}/verPdf.php?archivo=recursos/boletines/pdf/{anio}/{mes}/BO{dia}{mes}{anio}.pdf"
        return None

    async def search_decretos(self, numero: str, anio: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Busca Decretos del Poder Ejecutivo de Santa Fe en el SIN (src/busqueda.php).
        Manejo tolerante a fallos: devuelve los registros parseados con año exacto, fecha y sumario.
        """
        clean_num = "".join(filter(str.isdigit, str(numero)))
        clean_anio = "".join(filter(str.isdigit, str(anio))) if anio else ""

        if not clean_num:
            return []

        payload = {
            "tipoNorma": "2", # 2: Decretos
            "organismoSelect": "0",
            "numNorma": clean_num,
            "anio": clean_anio,
            "numExpediente": "",
            "textoNorma": "",
            "frase": "cualquiera",
            "fechaDesde": "",
            "fechaHasta": "",
            "action": "buscar",
            "pagina": "1",
            "ordenarPor": "2",
            "ordenBusqueda": "DESC"
        }

        try:
            async with httpx.AsyncClient(verify=False, timeout=DEFAULT_TIMEOUT) as client:
                r = await client.post(
                    f"{SIN_BASE_URL}/src/busqueda.php",
                    data=payload,
                    headers=self.headers
                )
                if r.status_code == 200 and len(r.text) > 400 and "Error" not in r.text and "0 resultados" not in r.text:
                    return self._parse_sin_results(r.text, default_num=clean_num)
        except Exception:
            pass

        return []

    def _parse_sin_results(self, html_content: str, default_num: str = "") -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html_content, "html.parser")
        results = []

        for tr in soup.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) >= 4:
                # Estructura del SIN:
                # c[0]: Número/Año (ej. '2439/2025')
                # c[1]: Norma Legal (ej. 'DECRETO')
                # c[2]: Descripción / Sumario
                # c[3]: Fecha (ej. '25-09-2025')
                c0 = cells[0].get_text(" ", strip=True)
                c1 = cells[1].get_text(" ", strip=True)
                c2 = cells[2].get_text(" ", strip=True)
                c3 = cells[3].get_text(" ", strip=True)

                if "Número" in c0 or "Norma" in c1:
                    continue

                # Extraer año de c0 (ej. '2439/2025') o de c3 (fecha)
                year_m = re.search(r"/(?: )?(\d{4})", c0) or re.search(r"(\d{4})", c3)
                year_str = year_m.group(1) if year_m else ""

                num_m = re.search(r"^(\d+)", c0)
                num_str = num_m.group(1) if num_m else default_num

                results.append({
                    "id": f"sin_{num_str}_{year_str}",
                    "tipo": "Decreto Provincial",
                    "numero": num_str,
                    "year": year_str,
                    "fecha": c3 if c3 and c3 != "-" else "No registrada",
                    "emisor": "Poder Ejecutivo de la Provincia de Santa Fe",
                    "jurisdiccion": "Santa Fe (Ejecutivo)",
                    "sumario": c2 or "Decreto del Poder Ejecutivo Provincial",
                    "url_portal": f"{SIN_BASE_URL}/index.php",
                    "url_boletin_buscar": f"{BOLETIN_BASE_URL}/"
                })

        return results

    async def get_temas_catalog(self) -> List[Dict[str, Any]]:
        """
        Obtiene el catálogo oficial de temas del Poder Ejecutivo de Santa Fe.
        """
        url = f"{SIN_BASE_URL}/src/ajaxServices.php?tipoNorma=2&accion=temas"
        try:
            async with httpx.AsyncClient(verify=False, timeout=DEFAULT_TIMEOUT) as client:
                r = await client.get(url, headers={"X-Requested-With": "XMLHttpRequest"})
                if r.status_code == 200 and r.text.startswith("["):
                    return r.json()
        except Exception:
            pass
        return []

    async def get_iniciadores_catalog(self) -> List[Dict[str, Any]]:
        """
        Obtiene el catálogo de organismos y ministerios emisores de Santa Fe.
        """
        url = f"{SIN_BASE_URL}/src/ajaxServices.php?tipoNorma=2&accion=iniciadores"
        try:
            async with httpx.AsyncClient(verify=False, timeout=DEFAULT_TIMEOUT) as client:
                r = await client.get(url, headers={"X-Requested-With": "XMLHttpRequest"})
                if r.status_code == 200 and r.text.startswith("["):
                    return r.json()
        except Exception:
            pass
        return []
