from backend.config import get_settings
from backend.runtime.desktop_server import run_desktop_server


def main() -> None:
    settings = get_settings()
    run_desktop_server(settings)


if __name__ == "__main__":
    main()
