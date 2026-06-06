"""Static rules-based technology detection from repo file contents."""
import json
import re
from dataclasses import dataclass
from typing import Optional

@dataclass
class TechMatch:
    name: str
    category: str
    confidence: float
    version: Optional[str]
    source_file: str


# package name → (display name, category)
_PKG_MAP: dict[str, tuple[str, str]] = {
    # Python web frameworks
    "fastapi": ("FastAPI", "Web Framework"),
    "flask": ("Flask", "Web Framework"),
    "django": ("Django", "Web Framework"),
    "starlette": ("Starlette", "Web Framework"),
    "aiohttp": ("aiohttp", "Web Framework"),
    "tornado": ("Tornado", "Web Framework"),
    "sanic": ("Sanic", "Web Framework"),
    "litestar": ("Litestar", "Web Framework"),
    "uvicorn": ("Uvicorn", "ASGI Server"),
    "gunicorn": ("Gunicorn", "WSGI Server"),
    # Data / ML
    "pandas": ("Pandas", "Data Analysis"),
    "numpy": ("NumPy", "Scientific Computing"),
    "scipy": ("SciPy", "Scientific Computing"),
    "matplotlib": ("Matplotlib", "Data Visualization"),
    "seaborn": ("Seaborn", "Data Visualization"),
    "plotly": ("Plotly", "Data Visualization"),
    "scikit-learn": ("Scikit-learn", "Machine Learning"),
    "sklearn": ("Scikit-learn", "Machine Learning"),
    "torch": ("PyTorch", "Deep Learning"),
    "pytorch": ("PyTorch", "Deep Learning"),
    "tensorflow": ("TensorFlow", "Deep Learning"),
    "keras": ("Keras", "Deep Learning"),
    "jax": ("JAX", "Deep Learning"),
    "transformers": ("HuggingFace Transformers", "NLP/AI"),
    "diffusers": ("HuggingFace Diffusers", "NLP/AI"),
    "sentence-transformers": ("Sentence Transformers", "NLP/AI"),
    # AI / LLM
    "anthropic": ("Anthropic Claude", "AI/LLM"),
    "openai": ("OpenAI", "AI/LLM"),
    "langchain": ("LangChain", "AI/LLM"),
    "langchain-core": ("LangChain", "AI/LLM"),
    "llama-index": ("LlamaIndex", "AI/LLM"),
    "llama_index": ("LlamaIndex", "AI/LLM"),
    "litellm": ("LiteLLM", "AI/LLM"),
    # Quant finance
    "zipline-tej": ("Zipline-TEJ", "Quant Finance"),
    "zipline": ("Zipline", "Quant Finance"),
    "backtrader": ("Backtrader", "Quant Finance"),
    "bt": ("bt", "Quant Finance"),
    "vectorbt": ("VectorBT", "Quant Finance"),
    "pyfolio": ("Pyfolio", "Quant Finance"),
    "alphalens": ("Alphalens", "Quant Finance"),
    "ta-lib": ("TA-Lib", "Quant Finance"),
    "ta": ("ta", "Quant Finance"),
    # Databases / ORM
    "sqlalchemy": ("SQLAlchemy", "ORM"),
    "alembic": ("Alembic", "Database Migrations"),
    "tortoise-orm": ("Tortoise ORM", "ORM"),
    "psycopg2": ("PostgreSQL", "Database"),
    "psycopg2-binary": ("PostgreSQL", "Database"),
    "psycopg": ("PostgreSQL", "Database"),
    "asyncpg": ("PostgreSQL", "Database"),
    "pymysql": ("MySQL", "Database"),
    "aiomysql": ("MySQL", "Database"),
    "aiosqlite": ("SQLite", "Database"),
    "sqlite3": ("SQLite", "Database"),
    "redis": ("Redis", "Cache/Database"),
    "aioredis": ("Redis", "Cache/Database"),
    "pymongo": ("MongoDB", "Database"),
    "motor": ("MongoDB", "Database"),
    "elasticsearch": ("Elasticsearch", "Search/Database"),
    "opensearch-py": ("OpenSearch", "Search/Database"),
    # Validation / serialisation
    "pydantic": ("Pydantic", "Data Validation"),
    "marshmallow": ("Marshmallow", "Data Validation"),
    "cerberus": ("Cerberus", "Data Validation"),
    # Testing
    "pytest": ("pytest", "Testing"),
    "unittest": ("unittest", "Testing"),
    "hypothesis": ("Hypothesis", "Testing"),
    "faker": ("Faker", "Testing"),
    "coverage": ("Coverage.py", "Testing"),
    # HTTP clients
    "httpx": ("HTTPX", "HTTP Client"),
    "requests": ("Requests", "HTTP Client"),
    "aiohttp": ("aiohttp", "HTTP Client"),
    # Task queues
    "celery": ("Celery", "Task Queue"),
    "dramatiq": ("Dramatiq", "Task Queue"),
    "rq": ("RQ", "Task Queue"),
    "apscheduler": ("APScheduler", "Task Scheduling"),
    # CLI / TUI
    "click": ("Click", "CLI"),
    "typer": ("Typer", "CLI"),
    "rich": ("Rich", "Terminal UI"),
    "textual": ("Textual", "Terminal UI"),
    # Config / misc
    "pyyaml": ("PyYAML", "Config"),
    "python-dotenv": ("dotenv", "Config"),
    "toml": ("TOML", "Config"),
    "loguru": ("Loguru", "Logging"),
    # Computer vision / OCR
    "paddlepaddle": ("PaddlePaddle", "Deep Learning"),
    "paddleocr": ("PaddleOCR", "Computer Vision"),
    "opencv-python": ("OpenCV", "Computer Vision"),
    "pillow": ("Pillow", "Image Processing"),
    # Browser automation
    "playwright": ("Playwright", "Browser Automation"),
    "selenium": ("Selenium", "Browser Automation"),
    "pyautogui": ("PyAutoGUI", "Automation"),
    # Scraping
    "beautifulsoup4": ("BeautifulSoup", "Web Scraping"),
    "scrapy": ("Scrapy", "Web Scraping"),
    "httpx": ("HTTPX", "HTTP Client"),
    # Data apps
    "streamlit": ("Streamlit", "Data App"),
    "gradio": ("Gradio", "ML Demo"),
    "dash": ("Plotly Dash", "Data App"),
    # Node.js / frontend
    "react": ("React", "UI Framework"),
    "vue": ("Vue", "UI Framework"),
    "svelte": ("Svelte", "UI Framework"),
    "@angular/core": ("Angular", "UI Framework"),
    "next": ("Next.js", "Web Framework"),
    "nuxt": ("Nuxt.js", "Web Framework"),
    "express": ("Express", "Web Framework"),
    "fastify": ("Fastify", "Web Framework"),
    "@nestjs/core": ("NestJS", "Web Framework"),
    "hono": ("Hono", "Web Framework"),
    "d3": ("D3.js", "Data Visualization"),
    "chart.js": ("Chart.js", "Data Visualization"),
    "three": ("Three.js", "3D Graphics"),
    "vite": ("Vite", "Build Tool"),
    "webpack": ("Webpack", "Build Tool"),
    "esbuild": ("esbuild", "Build Tool"),
    "jest": ("Jest", "Testing"),
    "vitest": ("Vitest", "Testing"),
    "axios": ("Axios", "HTTP Client"),
    "@anthropic-ai/sdk": ("Anthropic Claude", "AI/LLM"),
    "prisma": ("Prisma", "ORM"),
    "drizzle-orm": ("Drizzle ORM", "ORM"),
    "socket.io": ("Socket.IO", "WebSocket"),
    "graphql": ("GraphQL", "API"),
    # Go modules (partial match)
    "gin-gonic/gin": ("Gin", "Web Framework"),
    "labstack/echo": ("Echo", "Web Framework"),
    "gofiber/fiber": ("Fiber", "Web Framework"),
    # Rust crates
    "actix-web": ("Actix-web", "Web Framework"),
    "axum": ("Axum", "Web Framework"),
    "tokio": ("Tokio", "Async Runtime"),
    "serde": ("Serde", "Serialisation"),
}

_LANG_EXTS: dict[str, tuple[str, str]] = {
    ".py": ("Python", "Language"),
    ".js": ("JavaScript", "Language"),
    ".ts": ("TypeScript", "Language"),
    ".go": ("Go", "Language"),
    ".rs": ("Rust", "Language"),
    ".java": ("Java", "Language"),
    ".cs": ("C#", "Language"),
    ".cpp": ("C++", "Language"),
    ".cc": ("C++", "Language"),
    ".c": ("C", "Language"),
    ".rb": ("Ruby", "Language"),
    ".php": ("PHP", "Language"),
    ".swift": ("Swift", "Language"),
    ".kt": ("Kotlin", "Language"),
    ".scala": ("Scala", "Language"),
    ".ex": ("Elixir", "Language"),
    ".jl": ("Julia", "Language"),
    ".r": ("R", "Language"),
}

# Infrastructure / file presence detectors: (filename_or_subpath, tech, category)
_INFRA: list[tuple[str, str, str]] = [
    ("Dockerfile", "Docker", "DevOps/Container"),
    ("docker-compose.yml", "Docker Compose", "DevOps/Container"),
    ("docker-compose.yaml", "Docker Compose", "DevOps/Container"),
    (".github/workflows", "GitHub Actions", "CI/CD"),
    ("k8s/", "Kubernetes", "DevOps/Orchestration"),
    ("helm/", "Helm", "DevOps/Orchestration"),
    (".tf", "Terraform", "DevOps/IaC"),
    ("terraform/", "Terraform", "DevOps/IaC"),
    ("serverless.yml", "Serverless Framework", "DevOps/Serverless"),
    ("serverless.yaml", "Serverless Framework", "DevOps/Serverless"),
    ("Makefile", "Make", "Build Tool"),
    ("CMakeLists.txt", "CMake", "Build Tool"),
    (".github/dependabot.yml", "Dependabot", "DevOps/Security"),
    ("pyproject.toml", "Python", "Language"),
    ("requirements.txt", "Python", "Language"),
    ("setup.py", "Python", "Language"),
    ("package.json", "Node.js", "Runtime"),
    ("go.mod", "Go", "Language"),
    ("Cargo.toml", "Rust", "Language"),
    ("pom.xml", "Java", "Language"),
    ("build.gradle", "Java", "Language"),
    ("*.csproj", "C#", "Language"),
    ("tsconfig.json", "TypeScript", "Language"),
]


def _extract_version(line: str, pkg: str) -> Optional[str]:
    """Try to parse a version specifier from a requirements line."""
    m = re.search(r"[>=<~!^]{1,2}([0-9]+[^\s,;]*)", line)
    return m.group(1) if m else None


def detect_from_requirements(content: str, filename: str = "requirements.txt") -> list[TechMatch]:
    matches: list[TechMatch] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        pkg = re.split(r"[>=<!\s\[;]", line)[0].lower().strip()
        if pkg in _PKG_MAP:
            name, cat = _PKG_MAP[pkg]
            ver = _extract_version(line, pkg)
            matches.append(TechMatch(name, cat, 1.0, ver, filename))
    return matches


def detect_from_pyproject(content: str) -> list[TechMatch]:
    matches: list[TechMatch] = []
    in_deps = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if re.match(r"\[project\]", line):
            in_deps = False
        elif re.match(r"dependencies\s*=", line):
            in_deps = True
        elif in_deps and line.startswith("["):
            in_deps = False
        elif in_deps:
            pkg_str = line.strip(' "\',[]=')
            pkg = re.split(r"[>=<!\s\[;]", pkg_str)[0].lower().strip()
            if pkg and pkg in _PKG_MAP:
                name, cat = _PKG_MAP[pkg]
                ver = _extract_version(pkg_str, pkg)
                matches.append(TechMatch(name, cat, 0.95, ver, "pyproject.toml"))
    return matches


def detect_from_package_json(content: str) -> list[TechMatch]:
    matches: list[TechMatch] = []
    try:
        pkg_data = json.loads(content)
    except Exception:
        return matches
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        for pkg, ver_raw in pkg_data.get(section, {}).items():
            key = pkg.lower()
            if key in _PKG_MAP:
                name, cat = _PKG_MAP[key]
                ver = ver_raw.lstrip("^~>=<") if isinstance(ver_raw, str) else None
                confidence = 1.0 if section == "dependencies" else 0.8
                matches.append(TechMatch(name, cat, confidence, ver, "package.json"))
    return matches


def detect_from_go_mod(content: str) -> list[TechMatch]:
    matches: list[TechMatch] = []
    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("require") and not (line and line[0] not in "(/"):
            continue
        for partial, (name, cat) in _PKG_MAP.items():
            if "/" in partial and partial in line:
                m = re.search(r"v([0-9]+\.[0-9]+\.[0-9]+)", line)
                ver = m.group(1) if m else None
                matches.append(TechMatch(name, cat, 1.0, ver, "go.mod"))
    return matches


def detect_from_cargo_toml(content: str) -> list[TechMatch]:
    matches: list[TechMatch] = []
    in_deps = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if re.match(r"\[dependencies\]", line, re.I):
            in_deps = True
        elif line.startswith("[") and "dependencies" not in line.lower():
            in_deps = False
        elif in_deps:
            pkg = re.split(r"[\s=]", line)[0].strip('" ')
            if pkg in _PKG_MAP:
                name, cat = _PKG_MAP[pkg]
                m = re.search(r'"([0-9]+\.[0-9.]+)"', line)
                ver = m.group(1) if m else None
                matches.append(TechMatch(name, cat, 1.0, ver, "Cargo.toml"))
    return matches


def detect_from_file_list(file_paths: list[str]) -> list[TechMatch]:
    """Detect infra/language techs purely from file path presence."""
    matches: list[TechMatch] = []
    seen: set[str] = set()

    def _add(name: str, cat: str, src: str) -> None:
        if name not in seen:
            seen.add(name)
            matches.append(TechMatch(name, cat, 0.9, None, src))

    # Language detection from extensions
    ext_counts: dict[str, int] = {}
    for p in file_paths:
        ext = "." + p.rsplit(".", 1)[-1].lower() if "." in p else ""
        if ext in _LANG_EXTS:
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
    for ext, count in ext_counts.items():
        if count >= 1:
            name, cat = _LANG_EXTS[ext]
            _add(name, cat, f"{count} {ext} files")

    # Infra detection from filename presence
    path_set = set(file_paths)
    lower_set = {p.lower() for p in file_paths}
    for pattern, name, cat in _INFRA:
        if pattern.endswith("/"):
            if any(p.startswith(pattern) or f"/{pattern}" in p for p in lower_set):
                _add(name, cat, pattern)
        elif pattern.startswith("."):
            if any(p.endswith(pattern) for p in lower_set):
                _add(name, cat, pattern)
        else:
            if pattern.lower() in lower_set:
                _add(name, cat, pattern)

    return matches


def merge_matches(lists: list[list[TechMatch]]) -> list[TechMatch]:
    """Deduplicate by tech name, keeping highest confidence."""
    best: dict[str, TechMatch] = {}
    for group in lists:
        for m in group:
            if m.name not in best or m.confidence > best[m.name].confidence:
                best[m.name] = m
    return sorted(best.values(), key=lambda x: (-x.confidence, x.name))
