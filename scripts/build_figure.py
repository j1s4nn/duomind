"""Build LaTeX figure and convert to PNG."""

import subprocess
import sys
from pathlib import Path

import fitz  # PyMuPDF


def check_miktex():
    """Check if MiKTeX is installed."""
    try:
        result = subprocess.run(
            ["pdflatex", "--version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def build_figure():
    """Build the architecture figure."""
    tex_file = Path("docs/figures/architecture.tex")
    pdf_file = Path("docs/figures/architecture.pdf")
    png_file = Path("docs/images/architecture.png")

    # Check MiKTeX
    if not check_miktex():
        print("❌ MiKTeX not found. Please install MiKTeX from https://miktex.org")
        print("   Enable on-the-fly package installation during setup.")
        print("\n   Skipping figure build. The PNG is committed to the repo,")
        print("   so the README will work without rebuilding.")
        return False

    # Check tex file exists
    if not tex_file.exists():
        print(f"❌ {tex_file} not found")
        return False

    # Run pdflatex
    print(f"🔨 Building {tex_file}...")
    result = subprocess.run(
        [
            "pdflatex",
            "-interaction=nonstopmode",
            "-output-directory=docs/figures",
            str(tex_file),
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"❌ pdflatex failed:\n{result.stdout}\n{result.stderr}")
        return False

    if not pdf_file.exists():
        print(f"❌ PDF not generated at {pdf_file}")
        return False

    print(f"✅ PDF generated: {pdf_file}")

    # Convert to PNG
    print(f"🔨 Converting to PNG (200 DPI)...")
    try:
        doc = fitz.open(pdf_file)
        page = doc[0]
        mat = fitz.Matrix(200 / 72, 200 / 72)  # 200 DPI
        pix = page.get_pixmap(matrix=mat)

        png_file.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(png_file))

        print(f"✅ PNG generated: {png_file}")
        doc.close()

        return True

    except Exception as e:
        print(f"❌ PNG conversion failed: {e}")
        return False


if __name__ == "__main__":
    success = build_figure()
    sys.exit(0 if success else 1)
