import json
import re
import uuid
import time
from pathlib import Path
from urllib.parse import urlparse

INPUT_DIR = "."

DEFAULT_MODEL = "imported/perplexity-markdown"
USER_ID = "imported-perplexity-user"

def new_id():
    return str(uuid.uuid4())

def clean_md(text: str) -> str:
    text = re.sub(r'<img[^>]*>\s*', '', text, flags=re.IGNORECASE)

    text = re.sub(
        r'<span[^>]*display\s*:\s*none[^>]*>.*?</span>',
        '',
        text,
        flags=re.IGNORECASE | re.DOTALL
    )
    text = re.sub(
        r'<div[^>]*align\s*=\s*["\']?center["\']?[^>]*>\s*⁂\s*</div>',
        '',
        text,
        flags=re.IGNORECASE
    )
    text = re.sub(r'<div[^>]*>\s*⁂\s*</div>', '', text, flags=re.IGNORECASE)

    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def clean_user_text(text: str) -> str:
    text = text.strip()

    text = re.sub(r'^\s*TITLE\s+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+-\s+.*$', '', text)

    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'[ \t]+([.,;:!?])', r'\1', text)
    return text.strip(" -\n\t")

def pretty_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return url
    host = re.sub(r'^www\.', '', host)
    return host or url

def extract_footnotes(text: str):
    footnotes = {}

    pattern = re.compile(
        r'(?m)^\[\^([^\]]+)\]:\s+(https?://\S+)\s*$'
    )

    for match in pattern.finditer(text):
        footnotes[match.group(1)] = match.group(2).rstrip()

    text_wo_footnotes = pattern.sub('', text)
    return text_wo_footnotes.strip(), footnotes

def replace_footnote_refs(text: str, footnotes: dict):
    ref_pattern = re.compile(r'(?:\[\^([^\]]+)\])+')

    def repl(match):
        refs = re.findall(r'\[\^([^\]]+)\]', match.group(0))
        urls = []
        seen = set()

        for ref in refs:
            url = footnotes.get(ref)
            if url and url not in seen:
                urls.append(url)
                seen.add(url)

        if not urls:
            return ''

        links = []
        for url in urls:
            label = pretty_domain(url)
            links.append(f'[{label}]({url})')

        return " (Sources: " + ", ".join(links) + ")"

    return ref_pattern.sub(repl, text)

def clean_assistant_text(text: str) -> str:
    text = text.strip()

    # Remove real HTML leftovers
    text = re.sub(
        r'<span[^>]*display\s*:\s*none[^>]*>.*?</span>',
        '',
        text,
        flags=re.IGNORECASE | re.DOTALL
    )
    text = re.sub(
        r'<div[^>]*align\s*=\s*["\']?center["\']?[^>]*>\s*⁂\s*</div>',
        '',
        text,
        flags=re.IGNORECASE
    )
    text = re.sub(r'<div[^>]*>\s*⁂\s*</div>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<sup[^>]*>.*?</sup>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'</?(span|div|sup)[^>]*>', '', text, flags=re.IGNORECASE)

    # Remove plaintext export leftovers
    text = re.sub(r'\bspan\s+styledisplaynone[\d_]*span\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\bdiv\s+aligncenterdiv\b', '', text, flags=re.IGNORECASE)

    # Convert Perplexity footnote refs into visible clickable inline Markdown links
    text, footnotes = extract_footnotes(text)
    text = replace_footnote_refs(text, footnotes)

    # Remove remaining raw citation junk if any survived
    text = re.sub(r'(?<!`)\b\d+(?:_\d+){1,}\b(?!`)', '', text)
    text = re.sub(r'(?<=[A-Za-z).,!?:;\]])\d{4,}\b', '', text)
    text = re.sub(r'(?<!`)\[(\d{1,3})\](?!`)', '', text)
    text = re.sub(r'(?m)^\s*\d+(?:[_\d]*)\s*$', '', text)
    text = re.sub(r'(?m)^\s*\d+\s+https\S+\s*$', '', text)

    # Tidy spacing
    text = re.sub(r'[ \t]+([.,;:!?])', r'\1', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n[ \t]*\n[ \t]*\n+', '\n\n', text)

    return text.strip()

def parse_turns(md: str):
    md = clean_md(md)
    sections = [s.strip() for s in re.split(r'\n---\n', md) if s.strip()]
    turns = []

    for section in sections:
        m = re.match(r'^(?:#\s+|TITLE\s+)(.+?)\n+(.*)$', section, flags=re.DOTALL | re.IGNORECASE)
        if not m:
            continue

        user_text = clean_user_text(m.group(1).strip())
        assistant_text = clean_assistant_text(m.group(2).strip())

        if not user_text:
            continue
        if not assistant_text:
            assistant_text = "(No assistant content found in export)"

        turns.append({
            "user": user_text,
            "assistant": assistant_text
        })

    return turns

def build_chat(turns, title, base_ts):
    if not turns:
        raise ValueError("No turns could be parsed.")

    chat_id = new_id()
    message_map = {}
    message_list = []
    previous_assistant_id = None

    for i, turn in enumerate(turns):
        user_msg_id = new_id()
        assistant_msg_id = new_id()

        user_msg = {
            "id": user_msg_id,
            "parentId": previous_assistant_id,
            "childrenIds": [assistant_msg_id],
            "role": "user",
            "content": turn["user"].rstrip() + "\n",
            "models": [DEFAULT_MODEL],
            "timestamp": base_ts + i * 2
        }

        assistant_msg = {
            "id": assistant_msg_id,
            "parentId": user_msg_id,
            "childrenIds": [],
            "role": "assistant",
            "content": turn["assistant"],
            "model": DEFAULT_MODEL,
            "modelName": DEFAULT_MODEL,
            "modelIdx": 0,
            "timestamp": base_ts + i * 2 + 1,
            "done": True
        }

        if previous_assistant_id:
            message_map[previous_assistant_id]["childrenIds"] = [user_msg_id]

        message_map[user_msg_id] = user_msg
        message_map[assistant_msg_id] = assistant_msg
        message_list.extend([user_msg, assistant_msg])
        previous_assistant_id = assistant_msg_id

    return {
        "id": chat_id,
        "user_id": USER_ID,
        "title": title,
        "chat": {
            "id": "",
            "title": title,
            "models": [DEFAULT_MODEL],
            "params": {},
            "history": {
                "messages": message_map,
                "currentId": previous_assistant_id
            },
            "messages": message_list,
            "tags": [],
            "timestamp": base_ts * 1000,
            "files": []
        },
        "updated_at": base_ts + len(turns) * 2,
        "created_at": base_ts,
        "share_id": None,
        "archived": False,
        "pinned": False,
        "meta": {},
        "folder_id": None
    }

def title_from_file(path: Path, turns):
    if turns and turns[0]["user"]:
        return turns[0]["user"][:120]
    return path.stem.replace("-", " ").replace("_", " ").strip() or "Imported Perplexity Chat"

def main():
    input_dir = Path(INPUT_DIR)
    md_files = sorted(input_dir.glob("*.md"))

    if not md_files:
        raise FileNotFoundError(f"No .md files found in {input_dir.resolve()}")

    base_ts = int(time.time())
    converted_count = 0

    for idx, md_file in enumerate(md_files):
        md = md_file.read_text(encoding="utf-8")
        turns = parse_turns(md)

        if not turns:
            print(f"Skipping {md_file.name}: no turns parsed")
            continue

        title = title_from_file(md_file, turns)
        chat = build_chat(turns, title, base_ts + idx * 1000)

        output_path = md_file.parent / f"{md_file.stem}_converted.json"
        output_path.write_text(
            json.dumps([chat], ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        converted_count += 1
        print(f"Converted {md_file.name} -> {output_path.name}")

    if converted_count == 0:
        raise ValueError("No valid chats were converted.")

    print(f"\nWrote {converted_count} converted file(s)")

if __name__ == "__main__":
    main()
