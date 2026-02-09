# SecureChat Backend (FastAPI)

This is the backend server for **SecureChat**, a cybersecurity-focused chat application.
It provides authentication, encrypted message handling, and real-time communication.

---

## 📌 Requirements

- Python **3.9+**
- pip
- Virtual environment support (`venv`)

---

## ⚙️ Setup Instructions

1️⃣ Activate the virtual environment
Windows
venv\Scripts\activate
macOS / Linux
source venv/bin/activate

2️⃣ Install dependencies
pip install -r requirements.txt

3️⃣ Run the backend server
uvicorn main:app --reload --host 0.0.0.0 --port 8000