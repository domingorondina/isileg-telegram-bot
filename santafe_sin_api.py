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
DEFAULT_TIMEOUT = 10.0

# Caché en memoria para recuperar detalles de decretos del SIN al tocar botones
sin_detail_cache: Dict[str, Dict[str, Any]] = {}

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
                    results = self._parse_sin_results(r.text, default_num=clean_num)
                    # Guardar en caché para acceso rápido desde botones
                    for it in results:
                        sin_detail_cache[it["id"]] = it
                    return results
        except Exception:
            pass

        return []

    async def search_by_text(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Busca normas en el SIN de Santa Fe por texto / palabras clave.
        """
        if not query or len(query.strip()) < 3:
            return []

        payload = {
            "tipoNorma": "0", # 0: Todas las normas
            "organismoSelect": "0",
            "numNorma": "",
            "anio": "",
            "numExpediente": "",
            "textoNorma": query.strip(),
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
                    results = self._parse_sin_results(r.text)
                    for it in results:
                        sin_detail_cache[it["id"]] = it
                    return results[:limit]
        except Exception:
            pass

        return []

    def _parse_sin_results(self, html_content: str, default_num: str = "") -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html_content, "html.parser")
        results = []

        for tr in soup.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) >= 4:
                c0 = cells[0].get_text(" ", strip=True)
                c1 = cells[1].get_text(" ", strip=True)
                c2 = cells[2].get_text(" ", strip=True)
                c3 = cells[3].get_text(" ", strip=True)

                if "Número" in c0 or "Norma" in c1:
                    continue

                year_m = re.search(r"/(?: )?(\d{4})", c0) or re.search(r"(\d{4})", c3)
                year_str = year_m.group(1) if year_m else ""

                num_m = re.search(r"^(\d+)", c0)
                num_str = num_m.group(1) if num_m else default_num

                tipo_desc = c1 if c1 and c1 != "-" else "Decreto Provincial"
                if tipo_desc == "DECRETO":
                    tipo_desc = "Decreto Provincial"

                fecha_clean = c3 if c3 and c3 != "-" else "No registrada"
                pdf_boletin_url = self.build_boletin_pdf_url(fecha_clean)

                item_id = f"sin_{num_str}_{year_str}"
                results.append({
                    "id": item_id,
                    "tipo": tipo_desc,
                    "numero": num_str,
                    "year": year_str,
                    "fecha": fecha_clean,
                    "emisor": "Poder Ejecutivo de la Provincia de Santa Fe",
                    "jurisdiccion": "Santa Fe (Ejecutivo)",
                    "sumario": c2 or "Decreto del Poder Ejecutivo Provincial",
                    "url_portal": f"{SIN_BASE_URL}/index.php",
                    "url_boletin_pdf": pdf_boletin_url,
                    "url_boletin_buscar": f"{BOLETIN_BASE_URL}/"
                })

        return results

    def get_cached_detail(self, sin_id: str) -> Optional[Dict[str, Any]]:
        return sin_detail_cache.get(sin_id)
