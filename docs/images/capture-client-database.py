"""Capture docs/images/client-database-interface.png from a temporary synthetic database.

The database is created fresh in ``tmp/`` and holds only the three fictional clients that
appear in the README. A headless Chrome renders the running local form, and Pillow composes
the two views into one hero. Never point this script at a real client database.

    poetry run python docs/images/capture-client-database.py
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import okama_planner
from okama_planner.storage import PlannerStore

CLIENTS = [
    {
        "full_name": "Alex Morgan",
        "sex": "male",
        "birth_year": 1985,
        "email": "alex@example.invalid",
        "brokers": ["Example Broker A"],
        "primary_channel": "email",
        "crm_id": "00042-A",
        "ips_sent_at": "2026-09-15",
        "note": "Annual plan review",
    },
    {
        "full_name": "Priya Rao",
        "sex": "female",
        "birth_year": 1990,
        "email": "priya@example.invalid",
        "telegram": "@example_priya",
        "primary_channel": "telegram",
        "note": "First planning meeting",
    },
    {
        "full_name": "Jordan Lee",
        "birth_year": 1978,
        "email": "jordan@example.invalid",
        "phone": "+00 000 000-00-01",
        "brokers": [],
        "primary_channel": "email",
        "crm_id": "00043-J",
        "ips_sent_at": "2026-10-01",
        "note": "Retirement scenarios",
    },
]

MEETINGS = {
    "c-0001": [
        {
            "goal": "Reviewing goals",
            "date": "2026-10-15",
            "time": "14:00",
            "format": "online",
            "notes": "## What we discussed\n\nConfirmed priorities and the timeline for the goals.\n\n"
            "### Agreed\n\n- Prepare the list of assets\n- Confirm regular expenses\n",
        },
        {"goal": "Year-end review", "date": "2026-10-08", "time": "11:00", "format": "online",
         "notes": "Compared actual expenses with the plan."},
        {"goal": "Introduction", "date": "2026-10-01", "time": "", "format": "phone",
         "notes": "First call; agreed on the next meeting."},
    ],
    "c-0002": [
        {"goal": "First meeting", "date": "2026-10-14", "time": "10:30", "format": "in_person",
         "notes": "Collected the initial data for the plan."},
    ],
}

CANVAS = (2500, 1420)
CHROME = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")


def seed(path: Path) -> None:
    with PlannerStore.initialize(path) as store:
        for details in CLIENTS:
            store.create_client(details)
        for code, meetings in MEETINGS.items():
            for meeting in meetings:
                store.save_meeting(code, meeting)


def capture(url: str, target: Path, size: tuple[int, int]) -> Image.Image:
    width, height = size
    profile = target.parent / f"profile-{target.stem}"
    command = [
        CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
        "--hide-scrollbars", "--force-device-scale-factor=2", f"--window-size={width},{height}",
        f"--user-data-dir={profile}", f"--screenshot={target}", "--virtual-time-budget=5000", url,
    ]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return Image.open(target).convert("RGB")


def rounded(image: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *image.size), radius=radius, fill=255)
    out = image.convert("RGBA")
    out.putalpha(mask)
    return out


def window(content: Image.Image, width: int, chrome: int = 50) -> Image.Image:
    scale = width / content.width
    body = content.resize((width, round(content.height * scale)), Image.LANCZOS)
    card = Image.new("RGBA", (width, body.height + chrome), (255, 255, 255, 255))
    card.paste(body, (0, chrome))
    draw = ImageDraw.Draw(card)
    draw.rectangle((0, 0, width, chrome - 1), fill=(247, 249, 252, 255))
    draw.line((0, chrome, width, chrome), fill=(228, 234, 242, 255))
    for index, colour in enumerate(((255, 95, 87), (254, 188, 46), (40, 200, 64))):
        centre = (26 + index * 25, chrome // 2)
        draw.ellipse((centre[0] - 7, centre[1] - 7, centre[0] + 7, centre[1] + 7), fill=colour)
    draw.rounded_rectangle((420, 11, width - 420, chrome - 11), radius=(chrome - 22) // 2,
                           fill=(255, 255, 255, 255), outline=(226, 232, 240, 255))
    return rounded(card, 22)


def compose(journal: Image.Image, registry: Image.Image) -> Image.Image:
    background = Image.new("RGBA", CANVAS, (240, 245, 251, 255))
    gradient = Image.new("RGBA", CANVAS, (219, 230, 242, 255))
    mask = Image.linear_gradient("L").resize(CANVAS).point(lambda value: int(value * 0.9))
    background = Image.composite(gradient, background, mask)
    glow = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((-500, -600, 1800, 900), fill=(255, 255, 255, 120))
    background.alpha_composite(glow.filter(ImageFilter.GaussianBlur(130)))

    table = registry.crop((424, 455, 2455, 1040))
    ImageDraw.Draw(table).rectangle((0, 1014 - 455, table.width, table.height), fill=(255, 255, 255))

    for card, position in ((window(journal, 1700), (60, 80)), (window(table, 960, chrome=44), (1500, 880))):
        shadow = Image.new("RGBA", (card.width + 200, card.height + 200), (0, 0, 0, 0))
        shadow.paste(Image.new("RGBA", card.size, (15, 35, 60, 80)), (100, 118), card.split()[3])
        background.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(30)),
                                  (position[0] - 100, position[1] - 100))
        background.alpha_composite(card, position)
    return background.convert("RGB")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/images/client-database-interface.png"))
    args = parser.parse_args()
    if CHROME is None:
        print("Chrome or Chromium is required", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(dir="tmp") as work:
        workdir = Path(work)
        database = workdir / "clients.sqlite3"
        seed(database)
        package = str(Path(okama_planner.__file__).resolve().parent.parent)
        environment = {**os.environ, "PYTHONPATH": package + os.pathsep + os.environ.get("PYTHONPATH", "")}
        server = subprocess.Popen(
            [sys.executable, "-m", "okama_planner.client_form", "--database", str(database),
             "--language", "en"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=environment,
        )
        try:
            url = ""
            for line in server.stdout:
                match = re.search(r"http://127\.0\.0\.1:\d+/\S+/", line)
                if match:
                    url = match.group(0)
                    break
            if not url:
                raise RuntimeError("the local form did not print a capability URL")
            journal = capture(f"{url}?code=c-0001&view=meetings", workdir / "journal.png", (1440, 1000))
            registry = capture(url, workdir / "registry.png", (1440, 1000))
            compose(journal, registry).save(args.output, optimize=True)
        finally:
            server.terminate()
            server.wait(timeout=10)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
