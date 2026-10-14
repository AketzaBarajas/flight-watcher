"""Canales de aviso: consola, ntfy (push al móvil) y correo.

Las claves se leen de variables de entorno (.env en local, secrets en CI).
Nunca van en config.yaml ni en el repo.
"""

import json
import os
import smtplib
import urllib.request
from email.message import EmailMessage


class ErrorAviso(Exception):
    pass


def enviar(
    canales: tuple[str, ...],
    titulo: str,
    cuerpo: str,
    enlace: str | None = None,
    urgente: bool = False,
) -> list[str]:
    """Envía por todos los canales. Devuelve los errores (vacío = todo bien)."""
    errores = []
    for canal in canales:
        try:
            CANALES[canal](titulo, cuerpo, enlace, urgente)
        except KeyError:
            errores.append(f"canal desconocido '{canal}'")
        except Exception as e:
            errores.append(f"{canal}: {e}")
    return errores


def _consola(titulo: str, cuerpo: str, enlace: str | None, urgente: bool) -> None:
    print(f"\n=== {titulo} ===\n{cuerpo}")
    if enlace:
        print(enlace)


def _ntfy(titulo: str, cuerpo: str, enlace: str | None, urgente: bool) -> None:
    tema = os.environ.get("NTFY_TOPIC")
    if not tema:
        raise ErrorAviso("falta NTFY_TOPIC en .env")
    servidor = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
    mensaje = {
        "topic": tema,
        "title": titulo,
        "message": cuerpo,
        "tags": ["airplane"],
        "priority": 4 if urgente else 3,
    }
    if enlace:
        mensaje["click"] = enlace
    peticion = urllib.request.Request(
        servidor,
        data=json.dumps(mensaje).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(peticion, timeout=20) as r:
        if r.status != 200:
            raise ErrorAviso(f"ntfy respondió HTTP {r.status}")


def _email(titulo: str, cuerpo: str, enlace: str | None, urgente: bool) -> None:
    usuario = os.environ.get("EMAIL_USER")
    clave = os.environ.get("EMAIL_APP_PASSWORD")
    if not usuario or not clave:
        raise ErrorAviso("faltan EMAIL_USER / EMAIL_APP_PASSWORD en .env")
    msg = EmailMessage()
    msg["Subject"] = titulo
    msg["From"] = usuario
    msg["To"] = os.environ.get("EMAIL_TO", usuario)
    msg.set_content(cuerpo + (f"\n\n{enlace}" if enlace else ""))
    servidor = os.environ.get("EMAIL_SMTP", "smtp.gmail.com")
    with smtplib.SMTP_SSL(servidor, 465, timeout=30) as smtp:
        smtp.login(usuario, clave)
        smtp.send_message(msg)


CANALES = {"consola": _consola, "ntfy": _ntfy, "email": _email}
