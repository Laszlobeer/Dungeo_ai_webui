# 🐉 Dungeo_ai_webui

A fully local AI-powered Dungeon Master web UI — run solo RPG sessions with your own LLM!

---

## 🔍 Overview

**Dungeo_ai_webui** is a lightweight Python/Flask web application that connects to your local LLM (e.g., via [Ollama](https://ollama.ai/) or other supported engines) to simulate dynamic Dungeon Master sessions.

### Features:
- 🎲 **Local-first**: 100% offline, no external API calls
- 🌐 **Web UI**: Clean browser interface using Flask

Perfect for solo adventurers, creative writers, worldbuilders, and RPG prototypers!

---

## ⚙️ Features

- 🗺️ Dynamic storytelling: AI-driven world-building, narration, and encounters
- ❌ Banword filter: For SFW or thematic constraints

---

## 🛠️ Getting Started

### ✅ Prerequisites

- Python 3.8+
- A local LLM backend (Ollama)


### 📦 Installation

```bash
git clone https://github.com/Laszlobeer/Dungeo_ai_webui.git
cd Dungeo_ai_webui
pip install -r requirements.txt
```

### 🚀 Running the App

```bash
python app.py
```

Then open your browser and go to:

```
http://localhost:5000
```

---

## 📁 Project Structure

```
Dungeo_ai_webui/
├── app.py              # Main Flask server
├── templates/          # HTML templates
├── static/             # CSS, JS, images
├── banwords.txt        # Content filter list
└── requirements.txt    # Python dependencies
```

---

## 🎮 How to Use

1. Launch the app and open it in your browser.
2. Enter an initial prompt to set the scene.
3. The AI takes over as your Dungeon Master.
4. Respond in-character to shape the story.
5. Save and resume games anytime.

---

## 🧪 Customization

- Edit `banwords.txt` to control allowed content.
- Swap or modify LLM backends by editing `app.py`


---

## 🤝 Contributing

Pull requests are welcome! Feel free to:
- Suggest features
- Report bugs
- Improve UI/UX
- Add support for more LLM backends

---

## 📜 License

This project is licensed under the MIT License.  
See the [LICENSE](LICENSE) file for details.

---

## 💡 Acknowledgements

Created by **Laszlobeer**  

---

## 🧙 Quickstart Summary

```bash
git clone https://github.com/Laszlobeer/Dungeo_ai_webui.git
cd Dungeo_ai_webui
pip install -r requirements.txt
python app.py
```

Then open [http://localhost:5000](http://localhost:5000) and begin your quest!

## ☕ Support My Work

If you find this project helpful, consider [buying me a coffee](https://ko-fi.com/laszlobeer)!  
Your support helps me keep building and maintaining open-source tools. Thanks! ❤️

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/laszlobeer)

