import os
import random
import requests
import subprocess
import re
import logging
import datetime
from collections import defaultdict
from flask import Flask, render_template, request, session, jsonify, redirect, url_for
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'fallback_secret_key_12345')

# Configure logging
log_filename = f"rpg_adventure_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    filename=log_filename,
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

ALLTALK_API_URL = "http://localhost:7851/api/tts-generate"

# Initialize session data
def init_session():
    try:
        session.clear()
        session['censored'] = False
        session['conversation'] = ""
        session['last_ai_reply'] = ""
        session['character_name'] = "Alex"
        session['selected_genre'] = ""
        session['role'] = ""
        session['adventure_started'] = False
        session['player_choices'] = {
            "allies": [],
            "enemies": [],
            "discoveries": [],
            "reputation": 0,
            "resources": {},
            "factions": defaultdict(int),
            "completed_quests": [],
            "active_quests": [],
            "world_events": [],
            "consequences": []
        }
        session['ollama_model'] = ""
        session['installed_models'] = get_installed_models()
        session['tts_enabled'] = True
        logging.info("Session initialized successfully")
    except Exception as e:
        logging.error(f"Error initializing session: {str(e)}")

# Function to load banned words from file
def load_banwords():
    banwords = []
    try:
        if os.path.exists("banwords.txt"):
            with open("banwords.txt", "r", encoding="utf-8") as f:
                banwords = [line.strip().lower() for line in f if line.strip()]
            logging.info(f"Loaded {len(banwords)} banned words")
        else:
            logging.warning("banwords.txt not found. Using empty banwords list.")
    except Exception as e:
        logging.error(f"Error loading banwords: {e}")
    return banwords

# Load banned words at startup
BANWORDS = load_banwords()

# Function to retrieve installed Ollama models via CLI
def get_installed_models():
    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, check=True
        )
        lines = result.stdout.strip().splitlines()
        models = []
        for line in lines[1:]:  # Skip header line
            parts = line.split()
            if parts:
                models.append(parts[0])
        logging.info(f"Found {len(models)} installed models")
        return models
    except FileNotFoundError:
        logging.warning("Ollama not found. Using default models.")
        return ["llama3:instruct", "mistral", "phi3"]
    except Exception as e:
        logging.error(f"Error getting installed models: {e}")
        return ["llama3:instruct", "mistral", "phi3"]

# Role-specific starting scenarios
ROLE_STARTERS = {
    "Fantasy": {
        "Peasant": "You're toiling in the fields of a small village when",
        "Noble": "You're overseeing your estate's affairs when",
        "Mage": "You're studying ancient tomes in your tower when",
        "Knight": "You're training in the castle courtyard when",
        "Ranger": "You're tracking game in the deep forest when",
        "Thief": "You're casing a noble's manor in the city when",
        "Bard": "You're performing in a crowded tavern when",
        "Cleric": "You're tending to the sick in the temple when",
        "Assassin": "You're preparing for a contract in the shadows when",
        "Paladin": "You're praying at the altar of your deity when"
    },
    "Sci-Fi": {
        "Space Marine": "You're conducting patrol on a derelict space station when",
        "Scientist": "You're analyzing alien samples in your lab when",
        "Android": "You're performing system diagnostics on your ship when",
        "Pilot": "You're navigating through an asteroid field when",
        "Engineer": "You're repairing the FTL drive when",
        "Alien Diplomat": "You're negotiating with an alien delegation when",
        "Bounty Hunter": "You're tracking a target through a spaceport when",
        "Starship Captain": "You're commanding the bridge during warp travel when"
    },
    "Cyberpunk": {
        "Hacker": "You're infiltrating a corporate network when",
        "Street Samurai": "You're patrolling the neon-lit streets when",
        "Corporate Agent": "You're closing a deal in a high-rise office when",
        "Techie": "You're modifying cyberware in your workshop when",
        "Rebel Leader": "You're planning a raid on a corporate facility when",
        "Cyborg": "You're calibrating your cybernetic enhancements when"
    },
    "Post-Apocalyptic": {
        "Survivor": "You're scavenging in the ruins of an old city when",
        "Scavenger": "You're searching a pre-collapse bunker when",
        "Raider": "You're ambushing a convoy in the wasteland when",
        "Medic": "You're treating radiation sickness in your clinic when",
        "Cult Leader": "You're preaching to your followers at a ritual when"
    }
}

def get_role_starter(genre, role):
    """Get a role-specific starting scenario"""
    try:
        if genre in ROLE_STARTERS and role in ROLE_STARTERS[genre]:
            return ROLE_STARTERS[genre][role]

        generic_starters = {
            "Fantasy": "You're going about your daily duties when",
            "Sci-Fi": "You're performing routine tasks aboard your vessel when",
            "Cyberpunk": "You're navigating the neon-lit streets when",
            "Post-Apocalyptic": "You're surviving in the wasteland when"
        }

        return generic_starters.get(genre, "You find yourself in an unexpected situation when")
    except Exception as e:
        logging.error(f"Error in get_role_starter: {str(e)}")
        return "You find yourself in an unexpected situation when"

genres = {
    "1": ("Fantasy", [
        "Noble", "Peasant", "Mage", "Knight", "Ranger", "Alchemist", "Thief", "Bard",
        "Cleric", "Druid", "Assassin", "Paladin", "Warlock", "Monk", "Sorcerer",
        "Beastmaster", "Enchanter", "Blacksmith", "Merchant", "Gladiator", "Wizard"
    ]),
    "2": ("Sci-Fi", [
        "Space Marine", "Scientist", "Android", "Pilot", "Engineer", "Alien Diplomat",
        "Space Pirate", "Navigator", "Medic", "Robot Technician", "Cybernetic Soldier",
        "Explorer", "Astrobiologist", "Quantum Hacker", "Starship Captain",
        "Galactic Trader", "AI Specialist", "Terraformer", "Cyberneticist", "Bounty Hunter"
    ]),
    "3": ("Cyberpunk", [
        "Hacker", "Street Samurai", "Corporate Agent", "Techie", "Rebel Leader",
        "Drone Operator", "Synth Dealer", "Information Courier", "Augmentation Engineer",
        "Black Market Dealer", "Scumbag", "Police", "Cyborg"
    ]),
    "4": ("Post-Apocalyptic", [
        "Survivor", "Scavenger", "Mutant", "Trader", "Raider", "Medic",
        "Cult Leader", "Berserker", "Soldier"
    ]),
    "5": ("Random", [])
}

# Enhanced DM system prompt
DM_SYSTEM_PROMPT = """
You are a masterful Dungeon Master. Your role is to provide IMMEDIATE and PERMANENT consequences for every player action. Follow these rules:

1. ACTION-CONSEQUENCE SYSTEM:
   - EVERY player action MUST have an immediate consequence
   - Consequences must permanently change the game world
   - Describe consequences in the next response without delay
   - Small actions create ripple effects through the narrative

2. RESPONSE STRUCTURE:
   a) Immediate consequence (What happens right now)
   b) New situation (What the player sees now)
   c) Next challenges (What happens next)

3. WORLD EVOLUTION:
   - NPCs remember player choices and react accordingly
   - Environments change permanently based on actions
   - Player choices open/close future narrative paths
   - Resources are gained/lost permanently

Current World State:
{player_choices}
"""

def get_current_state(player_choices):
    """Generate a string representation of the current world state"""
    try:
        state = [
            f"### Current World State ###",
            f"Allies: {', '.join(player_choices['allies']) if player_choices['allies'] else 'None'}",
            f"Enemies: {', '.join(player_choices['enemies']) if player_choices['enemies'] else 'None'}",
            f"Reputation: {player_choices['reputation']}",
            f"Active Quests: {', '.join(player_choices['active_quests']) if player_choices['active_quests'] else 'None'}",
            f"Completed Quests: {', '.join(player_choices['completed_quests']) if player_choices['completed_quests'] else 'None'}",
        ]
        
        # Add resources if any exist
        if player_choices['resources']:
            state.append("Resources:")
            for resource, amount in player_choices['resources'].items():
                state.append(f"  - {resource}: {amount}")
        
        # Add faction relationships if any exist
        if player_choices['factions']:
            state.append("Faction Relationships:")
            for faction, level in player_choices['factions'].items():
                state.append(f"  - {faction}: {'+' if level > 0 else ''}{level}")
        
        # Add recent world events
        if player_choices['world_events']:
            state.append("Recent World Events:")
            for event in player_choices['world_events'][-3:]:
                state.append(f"  - {event}")
        
        # Add recent consequences
        if player_choices['consequences']:
            state.append("Recent Consequences:")
            for cons in player_choices['consequences'][-3:]:
                state.append(f"  - {cons}")
        
        return "\n".join(state)
    except Exception as e:
        logging.error(f"Error in get_current_state: {str(e)}")
        return "World state unavailable"

def get_ai_response(prompt, model, censored=False):
    try:
        if not model:
            return "No AI model selected. Please choose a model first."
            
        if censored:
            prompt += "\n[IMPORTANT: Content must be strictly family-friendly. Avoid any NSFW themes, violence, or mature content.]"

        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "num_predict": 500,  # Increased from 250 to 500
                    "stop": ["\n\n"],
                    "min_p": 0.05,
                    "top_k": 40
                }
            },
            timeout=120  # Increased timeout
        )
        response.raise_for_status()
        json_resp = response.json()
        return json_resp.get("response", "").strip()
    except requests.exceptions.ConnectionError:
        logging.error("Failed to connect to Ollama. Is it running?")
        return "Ollama is not responding. Please make sure Ollama is running."
    except requests.exceptions.Timeout:
        logging.warning("Ollama request timed out")
        return "The AI is taking too long to respond. Please try again."
    except Exception as e:
        logging.error(f"Unexpected error in get_ai_response: {e}")
        return "An error occurred while processing your request."

def speak(text, voice="FemaleBritishAccent_WhyLucyWhy_Voice_2.wav"):
    try:
        if not text.strip():
            return None

        payload = {
            "text_input": text,
            "character_voice_gen": voice,
            "narrator_enabled": "true",
            "narrator_voice_gen": "narrator.wav",
            "text_filtering": "none",
            "output_file_name": "output",
            "autoplay": "true",
            "autoplay_volume": "0.8"
        }
        response = requests.post(ALLTALK_API_URL, data=payload, timeout=5)
        response.raise_for_status()

        # Return the audio URL
        if response.ok:
            return f"{ALLTALK_API_URL}?output_file_name=output&autoplay=true"
        return None
    except requests.exceptions.ConnectionError:
        logging.error("Failed to connect to AllTalk TTS. Is it running?")
        return None
    except requests.exceptions.Timeout:
        logging.warning("TTS request timed out")
        return None
    except Exception as e:
        logging.error(f"Error in speech generation: {e}")
        return None

def sanitize_response(response, censored=False):
    if not response:
        return "The story continues..."

    try:
        # Only remove player prompt questions, not descriptive text
        question_phrases = [
            "what will you do", "how do you respond", "what do you do",
            "what is your next move", "what would you like to do",
            "what would you like to say", "how will you proceed"
        ]

        # Create a pattern that matches these phrases only at the end
        question_pattern = re.compile(
            r'(' + '|'.join(re.escape(phrase) for phrase in question_phrases) + r')[.?]?$', 
            re.IGNORECASE
        )
        
        # Remove prompt questions only if they appear at the end
        response = question_pattern.sub('', response).strip()
        
        # Remove any remaining trailing punctuation issues
        response = re.sub(r'[,.]+$', '', response).strip()

        # Add proper ending punctuation if missing
        if response and response[-1] not in ('.', '!', '?'):
            response += '.'

        # Censor content if needed
        if censored:
            for word in BANWORDS:
                if word:
                    pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
                    response = pattern.sub('****', response)

        return response
    except Exception as e:
        logging.error(f"Error sanitizing response: {str(e)}")
        return response

def process_narrative_command(user_input):
    """Process narrative commands that bend the story"""
    try:
        triggers = [
            "i bend the story to",
            "i reshape reality so that",
            "suddenly,",
            "miraculously,",
            "unexpectedly,",
            "against all odds,"
        ]
        
        for trigger in triggers:
            if user_input.lower().startswith(trigger):
                return f"Player (narrative command): {user_input}"
        
        return f"Player: {user_input}"
    except Exception as e:
        logging.error(f"Error in process_narrative_command: {str(e)}")
        return f"Player: {user_input}"

def update_world_state(action, response, player_choices):
    """Update world state based on player action and consequence"""
    try:
        # Record the consequence
        player_choices['consequences'].append(f"After '{action}': {response.split('.')[0]}")
        
        # Keep only the last 5 consequences
        if len(player_choices['consequences']) > 5:
            player_choices['consequences'] = player_choices['consequences'][-5:]
        
        # Update allies
        ally_matches = re.findall(r'(\b[A-Z][a-z]+\b) (?:joins|helps|saves|allies with)', response, re.IGNORECASE)
        for ally in ally_matches:
            if ally not in player_choices['allies']:
                player_choices['allies'].append(ally)
        
        # Update enemies
        enemy_matches = re.findall(r'(\b[A-Z][a-z]+\b) (?:dies|killed|falls|perishes)', response, re.IGNORECASE)
        for enemy in enemy_matches:
            if enemy in player_choices['allies']:
                player_choices['allies'].remove(enemy)
            if enemy in player_choices['enemies']:
                player_choices['enemies'].remove(enemy)
        
        # Update resources
        resource_matches = re.findall(r'(?:get|find|acquire|obtain) (\d+) (\w+)', response, re.IGNORECASE)
        for amount, resource in resource_matches:
            resource = resource.lower()
            if resource not in player_choices['resources']:
                player_choices['resources'][resource] = 0
            player_choices['resources'][resource] += int(amount)

        # Update world events
        world_event_matches = re.findall(r'(?:The|A) (\w+ \w+) (?:is|has been) (destroyed|created|changed|revealed)', response, re.IGNORECASE)
        for location, event in world_event_matches:
            player_choices['world_events'].append(f"{location} {event}")
    except Exception as e:
        logging.error(f"Error updating world state: {str(e)}")

@app.route('/')
def index():
    try:
        if 'censored' not in session:
            init_session()
        return render_template('index.html')
    except Exception as e:
        logging.error(f"Error in index route: {str(e)}")
        return "An error occurred. Please check the logs.", 500

@app.route('/model-selection', methods=['GET', 'POST'])
def model_selection():
    try:
        if request.method == 'POST':
            selected_model = request.form.get('model')
            if selected_model:
                session['ollama_model'] = selected_model
                return redirect(url_for('setup'))
            else:
                return render_template('model_selection.html', 
                                      models=session.get('installed_models', []),
                                      error="Please select a model")
        
        # GET request - show model selection
        return render_template('model_selection.html', 
                              models=session.get('installed_models', []))
    except Exception as e:
        logging.error(f"Error in model_selection route: {str(e)}")
        return redirect(url_for('index'))

@app.route('/change-model', methods=['POST'])
def change_model():
    try:
        selected_model = request.form.get('model')
        if selected_model and selected_model in session.get('installed_models', []):
            session['ollama_model'] = selected_model
            return jsonify({'status': 'success', 'message': f'Model changed to {selected_model}'})
        return jsonify({'status': 'error', 'message': 'Invalid model selection'})
    except Exception as e:
        logging.error(f"Error changing model: {str(e)}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

@app.route('/get-roles')
def get_roles():
    try:
        genre_id = request.args.get('genre')
        if genre_id in genres:
            return jsonify({"roles": genres[genre_id][1]})
        return jsonify({"roles": []})
    except Exception as e:
        logging.error(f"Error in get_roles: {str(e)}")
        return jsonify({"roles": []})

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    try:
        if not session.get('ollama_model'):
            return redirect(url_for('model_selection'))
            
        if request.method == 'POST':
            genre_id = request.form.get('genre')
            role = request.form.get('role')  # Get role name directly
            character_name = request.form.get('character_name', '').strip() or "Alex"
            
            logging.info(f"Received setup data: genre_id={genre_id}, role={role}, name={character_name}")
            
            if genre_id in genres:
                selected_genre, role_list = genres[genre_id]
                
                # Handle "Random" genre selection
                if selected_genre == "Random":
                    available = [v for k, v in genres.items() if k != "5"]
                    selected_genre, role_list = random.choice(available)
                
                # Validate role selection
                if not role or role not in role_list:
                    logging.warning(f"Invalid role selected: {role}. Valid roles: {role_list}")
                    role = random.choice(role_list) if role_list else "Adventurer"
                    logging.info(f"Using random role: {role}")
                
                session['selected_genre'] = selected_genre
                session['role'] = role
                session['character_name'] = character_name
                
                role_starter = get_role_starter(selected_genre, role)
                
                # Build initial context
                initial_context = (
                    f"### Adventure Setting ###\n"
                    f"Genre: {selected_genre}\n"
                    f"Player Character: {character_name} the {role}\n"
                    f"Starting Scenario: {role_starter}\n"
                )
                
                # Build full conversation with system prompt
                state_context = get_current_state(session['player_choices'])
                conversation = DM_SYSTEM_PROMPT.format(player_choices=state_context) + "\n\n" + initial_context
                
                # Get AI response
                ai_reply = get_ai_response(conversation + "\n\nDungeon Master: ", session['ollama_model'], session['censored'])
                
                if not ai_reply:
                    logging.error("AI returned empty response")
                    return jsonify({"status": "error", "message": "AI did not generate a response. Please try again."})
                
                # Handle AI error messages
                if ai_reply.startswith("Ollama is not responding") or \
                   ai_reply.startswith("The AI is taking too long") or \
                   ai_reply.startswith("An error occurred"):
                    logging.error(f"AI error: {ai_reply}")
                    return jsonify({"status": "error", "message": ai_reply})
                
                ai_reply = sanitize_response(ai_reply, session['censored'])
                session['conversation'] = conversation + "\n\nDungeon Master: " + ai_reply
                session['last_ai_reply'] = ai_reply
                session['player_choices']['consequences'].append(f"Start: {ai_reply.split('.')[0]}")
                session['adventure_started'] = True
                
                # Generate TTS audio if needed
                audio_url = speak(ai_reply) if session.get('tts_enabled', True) else None
                
                return jsonify({
                    "status": "success",
                    "message": ai_reply,
                    "audio_url": audio_url
                })
            
            return jsonify({"status": "error", "message": "Invalid genre selection"})
        
        # GET request - render setup page
        return render_template('setup.html', genres=genres)
    except Exception as e:
        logging.error(f"Error in setup route: {str(e)}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

@app.route('/game')
def game():
    try:
        if not session.get('adventure_started', False):
            return redirect(url_for('index'))
            
        # Add system prompt to context
        system_prompt = DM_SYSTEM_PROMPT.format(
            player_choices=get_current_state(session['player_choices'])
        )
        
        return render_template('game.html', system_prompt=system_prompt)
    except Exception as e:
        logging.error(f"Error in game route: {str(e)}")
        return redirect(url_for('index'))

@app.route('/command', methods=['POST'])
def process_command():
    try:
        if not session.get('adventure_started', False):
            return jsonify({"status": "error", "message": "Adventure not started"})
        
        user_input = request.form.get('command', '').strip()
        if not user_input:
            return jsonify({"status": "error", "message": "Empty command"})
        
        cmd = user_input.lower()
        
        # Handle special commands
        if cmd == "/censored":
            session['censored'] = not session['censored']
            mode = "ON (SFW)" if session['censored'] else "OFF (NSFW)"
            return jsonify({
                "status": "info",
                "message": f"Content filtering {mode}."
            })
            
        if cmd == "/consequences":
            consequences = session['player_choices']['consequences'][-5:]
            return jsonify({
                "status": "info",
                "message": "\n".join([f"{i+1}. {c}" for i, c in enumerate(consequences)]) if consequences else "No consequences recorded yet."
            })
            
        if cmd == "/redo":
            if session['last_ai_reply']:
                # Find the last Dungeon Master response
                last_dm_pos = session['conversation'].rfind("Dungeon Master:")
                if last_dm_pos != -1:
                    session['conversation'] = session['conversation'][:last_dm_pos].rstrip()
                
                # Rebuild prompt with current state
                state_context = get_current_state(session['player_choices'])
                full_conversation = (
                    f"{DM_SYSTEM_PROMPT.format(player_choices=state_context)}\n\n"
                    f"{session['conversation']}"
                )
                
                ai_reply = get_ai_response(full_conversation, session['ollama_model'], session['censored'])
                if ai_reply:
                    ai_reply = sanitize_response(ai_reply, session['censored'])
                    session['conversation'] += f"\nDungeon Master: {ai_reply}"
                    session['last_ai_reply'] = ai_reply
                    
                    audio_url = speak(ai_reply) if session.get('tts_enabled', True) else None
                    
                    return jsonify({
                        "status": "success",
                        "message": ai_reply,
                        "audio_url": audio_url
                    })
            return jsonify({"status": "error", "message": "Nothing to redo"})
        
        if cmd == "/save":
            try:
                with open("adventure.txt", "w", encoding="utf-8") as f:
                    f.write(session['conversation'])
                    f.write("\n\n### Persistent World State ###\n")
                    f.write(get_current_state(session['player_choices']))
                return jsonify({"status": "success", "message": "Adventure saved to adventure.txt"})
            except Exception as e:
                logging.error(f"Error saving adventure: {e}")
                return jsonify({"status": "error", "message": "Error saving adventure"})
        
        # Process regular command
        formatted_input = process_narrative_command(user_input)
        
        # Build conversation with current world state
        state_context = get_current_state(session['player_choices'])
        full_conversation = (
            f"{DM_SYSTEM_PROMPT.format(player_choices=state_context)}\n\n"
            f"{session['conversation']}\n"
            f"{formatted_input}\n"
            "Dungeon Master:"
        )
        
        # Get AI response
        ai_reply = get_ai_response(full_conversation, session['ollama_model'], session['censored'])
        
        if not ai_reply:
            return jsonify({"status": "error", "message": "No response from AI"})
            
        ai_reply = sanitize_response(ai_reply, session['censored'])
        session['conversation'] += f"\n{formatted_input}\nDungeon Master: {ai_reply}"
        session['last_ai_reply'] = ai_reply
        
        # Update world state
        update_world_state(user_input, ai_reply, session['player_choices'])
        
        # Generate TTS audio if needed
        audio_url = speak(ai_reply) if session.get('tts_enabled', True) else None
        
        return jsonify({
            "status": "success",
            "message": ai_reply,
            "consequence": ai_reply.split('.')[0],
            "world_state": get_current_state(session['player_choices']),
            "audio_url": audio_url
        })
        
    except Exception as e:
        logging.error(f"Error in command route: {str(e)}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

@app.route('/help')
def show_help():
    try:
        return render_template('help.html')
    except Exception as e:
        logging.error(f"Error in help route: {str(e)}")
        return "Help page unavailable", 500

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    print(f"Starting RPG Adventure WebUI on port {port}...")
    print(f"Debug mode: {'ON' if debug_mode else 'OFF'}")
    
    try:
        app.run(
            host='0.0.0.0', 
            port=port,
            debug=debug_mode,
            use_reloader=debug_mode
        )
    except Exception as e:
        logging.critical(f"Failed to start server: {str(e)}")