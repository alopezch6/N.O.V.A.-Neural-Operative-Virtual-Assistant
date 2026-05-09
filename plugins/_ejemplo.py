# plugins/_ejemplo.py — Plantilla de referencia para plugins de NOVA
# Los archivos con _ al inicio NO se cargan automáticamente.
# Copia este archivo, quita el _, y adáptalo.

DESCRIPTION = "Muestra el uso de disco de Oracle"

# Frases que el usuario escribiría para activar este plugin.
# Cuantas más variantes, mejor reconocimiento.
KEYWORDS = [
    "uso de disco",
    "cuánto disco queda",
    "cuanto disco queda",
    "espacio en disco",
    "disco oracle",
    "disco disponible",
]

# True si la acción es destructiva o irreversible (kill, delete, shutdown...)
# En ese caso NOVA pedirá confirmación antes de ejecutar.
NEEDS_CONFIRM = False


def ejecutar(params: dict) -> str:
    # params["text"] contiene el mensaje original del usuario (por si necesitas parsear algo)
    import subprocess
    try:
        r = subprocess.run(
            ["df", "-h", "/"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            return f"Uso de disco en Oracle:\n```\n{r.stdout.strip()}\n```"
        return f"Error al consultar disco: {r.stderr.strip()}"
    except Exception as e:
        return f"Error: {e}"
