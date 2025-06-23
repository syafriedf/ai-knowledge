import io, os
import openai
import streamlit as st
from dotenv import load_dotenv

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from pdfminer.high_level import extract_text
import docx

# ------------------------ SETUP ------------------------
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
SERVICE_ACCOUNT_FILE = "credentials.json"

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
drive = build("drive", "v3", credentials=creds)

# ------------------------ FUNCTIONS ------------------------
def get_first_file_in_folder(folder_id):
    resp = drive.files().list(q=f"'{folder_id}' in parents and trashed=false", fields="files(id,name)", pageSize=1).execute()
    files = resp.get("files", [])
    if not files:
        st.error("📂 Folder kosong di Google Drive."); st.stop()
    return files[0]["id"], files[0]["name"]

def download_to_buffer(file_id):
    req = drive.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    buf.seek(0)
    return buf

def extract_text_from_buffer(buf, name):
    if name.lower().endswith(".pdf"):
        return extract_text(buf)
    elif name.lower().endswith((".docx", ".doc")):
        doc = docx.Document(buf)
        return "\n".join(p.text for p in doc.paragraphs)
    else:
        st.error("Format file tidak didukung."); st.stop()

def generate_bubbles(snippet, fname):
    prompt = f"""
Berdasarkan dokumen berikut ({fname}), buat 3 pertanyaan bubble chat yang relevan dan singkat:
\"\"\"{snippet}\"\"\"
Contoh:
- Berikan isi SOP dari miss order dan bagan nya
- Siapa Penanggung Jawab Pengeluaran Biaya Promosi
- Apa saja tugas SOP Salesman
"""
    try:
        response = openai.chat.completions.create(
            model=st.session_state.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=200
        )
        lines = response.choices[0].message.content.strip().split("\n")
        raw = [l.lstrip("-0123456789. ").strip() for l in lines]
        bubbles = [b for b in raw if b and (b.endswith("?") or b.lower().startswith(("siapa", "apa", "bagaimana", "mengapa", "kapan", "dimana")))]
        return bubbles[:3]
    except Exception as e:
        st.warning(f"❗ Gagal membuat bubble chat: {e}")
        return []

def generate_followup_bubbles(last_reply):
    prompt = f"""
Berdasarkan jawaban berikut ini, buat 3 pertanyaan lanjutan yang bisa ditanyakan user secara singkat dan relevan:
\"\"\"{last_reply}\"\"\"
Jawaban harus berupa pertanyaan singkat seperti:
- Siapa penanggung jawabnya?
- Apa langkah berikutnya?
- Bisa dijelaskan lebih lanjut?
"""
    try:
        response = openai.chat.completions.create(
            model=st.session_state.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=200
        )
        lines = response.choices[0].message.content.strip().split("\n")
        bubbles = [l.lstrip("-0123456789. ").strip() for l in lines]
        filtered = [b for b in bubbles if b and (
            b.endswith("?") or b.lower().startswith(("siapa", "apa", "bagaimana", "mengapa", "kapan", "dimana"))
        )]
        return filtered[:3]
    except Exception:
        return []

# ------------------------ INIT STATE ------------------------
st.set_page_config(page_title="Brainee - AI Knowledge Intelligence", layout="wide")

def init_state():
    if "model" not in st.session_state:
        st.session_state.model = "gpt-3.5-turbo"
    if "conversation" not in st.session_state:
        st.session_state.conversation = [
            {"role": "system", "content": "Kamu adalah asisten yang membantu dengan ramah dan to the point."}
        ]
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "selected" not in st.session_state:
        st.session_state.selected = None
    if "fid" not in st.session_state:
        fid, fname = get_first_file_in_folder(FOLDER_ID)
        buf = download_to_buffer(fid)
        text = extract_text_from_buffer(buf, fname)
        snippet = text[:2000] + "..." if len(text) > 2000 else text
        st.session_state.fid = fid
        st.session_state.fname = fname
        st.session_state.text_snippet = snippet
    if "bubbles" not in st.session_state:
        st.session_state.bubbles = generate_bubbles(
            st.session_state.text_snippet, st.session_state.fname
        )

init_state()

# ------------------------ SIDEBAR ------------------------
with st.sidebar:
    st.header("📚 Navigasi")
    if st.button("🆕 New Chat"):
        st.session_state.conversation = [
            {"role": "system", "content": "Kamu adalah asisten yang membantu dengan ramah dan to the point."}
        ]
        st.session_state.bubbles = generate_bubbles(
            st.session_state.text_snippet, st.session_state.fname
        )
        st.session_state.selected = None
        st.rerun()

    st.markdown("### 🕘 Riwayat Chat")
    for idx, hist in enumerate(st.session_state.chat_history):
        label = hist.get("title", f"Chat #{idx+1}")
        if st.button(f"📄 {label}", key=f"hist_{idx}"):
            st.session_state.conversation = hist["conversation"]
            st.session_state.bubbles = hist["bubbles"]
            st.session_state.selected = None
            st.rerun()
    
    st.markdown("---")
    st.markdown("<p style='text-align: center; font-size: 12px; color: grey;'>© 2025 Analyset</p>", unsafe_allow_html=True)

# ------------------------ UI ------------------------
st.title("🤖 AI Knowledge by Analyset")
st.selectbox("🧠 Pilih Model", ["gpt-3.5-turbo", "gpt-4"], key="model")

# Chat history
for msg in st.session_state.conversation[1:]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Bubble awal (sebelum user prompt)
if st.session_state.bubbles:
    st.divider()
    cols = st.columns(len(st.session_state.bubbles))
    for i, b in enumerate(st.session_state.bubbles):
        if b and cols[i].button(b, key=f"bubble_{i}_{b}"):
            st.session_state.selected = b
            st.session_state.bubbles = []  # langsung hilang setelah klik
            st.rerun()

# Chat input
user_input = st.session_state.get("selected", None)
manual_input = st.chat_input("Ketik pertanyaan Anda di sini...")
if user_input is None:
    user_input = manual_input

# ------------------------ PROCESS ------------------------
if user_input:
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state.conversation.append({"role": "user", "content": user_input})

    with st.chat_message("assistant"):
        with st.spinner("✍️ Mengetik jawaban..."):
            response = openai.chat.completions.create(
                model=st.session_state.model,
                messages=st.session_state.conversation + [
                    {"role": "user", "content": f"{user_input}\n\nJika memungkinkan, berikan jawaban dalam penjelasan kemudian diikuti poin-poin singkat, dan berikan gambar nya jika user spesifik meminta bagan."}
                ],
                temperature=0.7,
                max_tokens=500
            )
            reply = response.choices[0].message.content.strip()
            st.markdown(reply)

        followups = generate_followup_bubbles(reply)
        if followups:
            st.divider()
            cols = st.columns(len(followups))
            for i, b in enumerate(followups):
                if cols[i].button(b, key=f"followup_{i}_{b}"):
                    st.session_state.selected = b
                    st.session_state.bubbles = []
                    st.rerun()
        st.session_state.bubbles = followups

    st.session_state.conversation.append({"role": "assistant", "content": reply})

    # ✅ Simpan riwayat hanya saat pertama kali user prompt
    if len(st.session_state.conversation) == 3:  # system + user + assistant
        title = user_input[:40]
        st.session_state.chat_history.append({
            "title": title,
            "conversation": st.session_state.conversation.copy(),
            "bubbles": st.session_state.bubbles.copy()
        })

    st.session_state.selected = None
