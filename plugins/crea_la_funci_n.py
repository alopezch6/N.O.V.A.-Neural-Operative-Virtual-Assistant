import subprocess, os, sys, json, re
from pathlib import Path

DESCRIPTION = "Crea un archivo .py con la función especificada por el usuario"
KEYWORDS = ["crea la función", "generar función", "escribir función", "añadir función"]
NEEDS_CONFIRM = False

def ejecutar(params: dict) -> str:
    import sys, os, pathlib, re, json
    try:
        text = params.get("text", "")
        # Extraer todo después de la frase clave "crea la función"
        match = re.search(r"crea la función\s*(.*)", text, re.IGNORECASE)
        if not match:
            return "No se encontró la descripción de la función."
        func_body = match.group(1).strip()
        if not func_body.lower().startswith("def "):
            func_body = "def " + func_body
        # Asegurarse de que termina con salto de línea
        func_body = func_body.rstrip() + "\n"
        # Ruta del archivo
        file_path = pathlib.Path.cwd() / "generated_function.py"
        # Escribir (añadir) la función al archivo
        with open(file_path, "a", encoding="utf-8") as f:
            f.write("\n" + func_body)
        return f"Función guardada en {file_path}"
    except Exception as e:
        return f"Error al crear la función: {e}"