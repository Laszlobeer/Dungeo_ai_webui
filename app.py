import os
import random
import requests
import subprocess
import re
import logging
import datetime
import time
import traceback
from collections import defaultdict
from flask import Flask, render_template, request, session, jsonify, redirect, url_for, Response
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

OLLAMA_API_URL = "http://localhost:11434/api/generate"
OLLAMA_HEALTH_URL = "http://localhost:11434/api/tags"
ALLTALK_API_URL = os.getenv('TTS_API_URL', 'http://localhost:7851/api/tts-generate')
TTS_AUDIO_BASE_URL = os.getenv('TTS_AUDIO_URL', 'http://localhost:7851/outputs')

# Enhanced DM system prompt with player freedom
DM_SYSTEM_PROMPT = """

You are a masterful Dungeon Master guiding {character_name}, a {role} in a {genre} adventure. 
Craft IMMEDIATE and PERMANENT consequences for every action. Follow these rules:

1. PLAYER FREEDOM:
   - Players can attempt ANY action they imagine, no matter how unconventional
   - Always accept player actions as valid starting points
   - Never say "you can't do that" - instead show consequences
   - Adapt the world to incorporate player choices organically

2. ACTION-CONSEQUENCE SYSTEM:
   - Describe ONLY the outcomes of player actions and world events
   - Consequences must logically follow from the action
   - Describe consequences naturally within your narration
   - Small actions create ripple effects through the narrative

3. RESPONSE STYLE:
   - Respond in natural narrative prose, NEVER in bullet points
   - Weave consequences seamlessly into your descriptions
   - NEVER use labels like "a) b) c)" or "Immediate consequence:"
   - Show, don't tell - demonstrate consequences through storytelling
   - Focus on describing environments, NPC actions, and world reactions

4. WORLD EVOLUTION:
   - NPCs remember player choices and react accordingly
   - Environments change permanently based on actions
   - Player choices open/close future narrative paths
   - Resources are gained/lost permanently

Current World State:
{player_choices}
"""

def get_available_voices():
    """Scan available TTS voices with better detection"""
    voices = []
    voice_exts = ('.wav', '.mp3', '.ogg', '.flac')
    
    # 1. Check API endpoint first
    try:
        response = requests.get("http://localhost:7851/api/get-voices", timeout=3)
        if response.status_code == 200:
            voice_data = response.json()
            # Format: "Voice Name (filename.extension)"
            for voice in voice_data:
                if 'voice' in voice:
                    # Extract base name without extension
                    base_name = os.path.splitext(voice['voice'])[0]
                    # Replace underscores and dashes with spaces
                    clean_name = re.sub(r'[-_]', ' ', base_name)
                    # Capitalize each word
                    clean_name = clean_name.title()
                    voices.append(f"{clean_name} ({voice['voice']})")
            logging.info(f"Found {len(voices)} voices via API")
            return voices
    except Exception as e:
        logging.warning(f"API voice scan failed: {str(e)}")
    
    # 2. Scan common voice directories
    voice_dirs = [
        "/app/voices",          # Common Docker path
        "/usr/src/app/voices",   # AllTalk default
        os.path.join(os.getcwd(), "voices"),  # Local development
        "/voices"                # Alternative Docker path
    ]
    
    for voice_dir in voice_dirs:
        try:
            if os.path.exists(voice_dir):
                logging.info(f"Scanning voice directory: {voice_dir}")
                for file in os.listdir(voice_dir):
                    if file.lower().endswith(voice_exts):
                        # Extract base name without extension
                        base_name = os.path.splitext(file)[0]
                        # Replace underscores and dashes with spaces
                        clean_name = re.sub(r'[-_]', ' ', base_name)
                        # Capitalize each word
                        clean_name = clean_name.title()
                        voices.append(f"{clean_name} ({file})")
                if voices:
                    logging.info(f"Found {len(voices)} voices in {voice_dir}")
                    return voices
        except Exception as e:
            logging.warning(f"Error scanning {voice_dir}: {str(e)}")
    
    # 3. Fallback to known English voices
    fallback_voices = [
        "British Female (FemaleBritishAccent_WhyLucyWhy_Voice_2.wav)",
        "American Female (FemaleAmericanAccent_WhyLucyWhy_Voice_1.wav)",
        "American Male (MaleAmericanAccent_WhyLucyWhy_Voice_1.wav)"
    ]
    logging.info("Using fallback voices")
    return fallback_voices

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
        session['theme'] = "fantasy"  # Default theme
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
            "consequences": [],
            "player_creations": []  # Track player-created entities
        }
        session['installed_models'] = get_installed_models()
        
        # Set default model if available
        if session['installed_models']:
            session['ollama_model'] = session['installed_models'][0]
        else:
            session['ollama_model'] = "llama3:instruct"
            
        session['tts_enabled'] = True
        
        # Get available voices and set the default
        session['available_voices'] = get_available_voices()
        session['tts_voice'] = session['available_voices'][0] if session['available_voices'] else ""
        
        logging.info("Session initialized successfully")
    except Exception as e:
        logging.error(f"Error initializing session: {str(e)}")
        # Set fallback values
        session['available_voices'] = [
            "British Female (FemaleBritishAccent_WhyLucyWhy_Voice_2.wav)",
            "American Female (FemaleAmericanAccent_WhyLucyWhy_Voice_1.wav)"
        ]
        session['tts_voice'] = session['available_voices'][0]
        session['ollama_model'] = "llama3:instruct"  # Fallback model
        session['installed_models'] = ["llama3:instruct"]

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
        # First try API method
        response = requests.get(OLLAMA_HEALTH_URL, timeout=5)
        if response.status_code == 200:
            models = [model['model'] for model in response.json().get('models', []) 
                     if 'model' in model]
            logging.info(f"Found {len(models)} models via API")
            return models
    except Exception as e:
        logging.warning(f"API model fetch failed: {e}")

    try:
        # Fallback to CLI method with improved parsing
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, check=True
        )
        lines = result.stdout.strip().splitlines()
        models = []
        if len(lines) > 1:  # Skip header line
            for line in lines[1:]:
                parts = line.split()
                if parts:
                    # Extract model name with tag
                    model_name = parts[0]
                    # Handle cases where model name has spaces
                    if ':' in model_name:
                        models.append(model_name)
                    else:
                        # Try to find the model name with tag in subsequent parts
                        for part in parts[1:]:
                            if ':' in part:
                                models.append(f"{model_name}:{part.split(':')[1]}")
                                break
                        else:
                            models.append(model_name)
        logging.info(f"Found {len(models)} installed models via CLI")
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
        "Noble": "You're presiding over the royal court when a bloodied messenger bursts through the doors, gasping about an invading force at the city gates.",
        "Peasant": "You're harvesting turnips in muddy fields when a meteor crashes nearby, revealing a pulsating crystalline artifact.",
        "Mage": "While translating forbidden runes in your sanctum, the arcane wards suddenly shatter as shadowy tendrils burst from your summoning circle.",
        "Knight": "During your oath-swearing ceremony, assassins leap from the cathedral rafters, their blades aimed at the king.",
        "Ranger": "Tracking a wounded direwolf, you stumble upon an elven massacre site - arrows still quivering in ancient oaks.",
        "Alchemist": "Your volatile mixture begins glowing with unearthly light seconds before the laboratory door explodes inward.",
        "Thief": "Midway through cracking the Duke's vault, magical alarms wail as armored boots echo down the marble corridor.",
        "Bard": "During your tavern performance, a dying soldier collapses on stage, pressing a bloodstained map into your hands.",
        "Cleric": "While administering last rites, the corpse's eyes snap open, speaking with your deity's unmistakable voice.",
        "Druid": "The ancient forest whispers warnings moments before unnatural flames erupt across the sacred grove.",
        "Assassin": "Poised to eliminate your target, their bodyguard whispers your childhood name - a secret only family should know.",
        "Paladin": "Your holy symbol cracks during dawn prayers as an eclipse plunges the temple into unnatural darkness.",
        "Warlock": "Your patron's voice screams inside your skull as celestial fire rains upon the city.",
        "Monk": "Meditating atop the Thousand-Step Stairs, you sense tremors of approaching war machines breaching the mountain pass.",
        "Sorcerer": "Wild magic surges uncontrollably from your fingertips just as the Mage Hunters kick down your door.",
        "Beastmaster": "Your tamed griffons shriek in unison as an obsidian airship punctures the clouds above your menagerie.",
        "Enchanter": "Every enchanted item in your shop activates simultaneously, pointing toward the castle dungeons.",
        "Blacksmith": "The legendary sword you're reforging glows white-hot and levitates as spectral warriors materialize in your forge.",
        "Merchant": "Your prized spice shipment transforms into writhing serpents as city guards accuse you of witchcraft.",
        "Gladiator": "Mid-duel, the arena floor collapses, revealing catacombs filled with chained primordial beasts.",
        "Wizard": "Your scrying pool shows invading armies from three kingdoms converging on your tower."
    },
    "Sci-Fi": {
        "Space Marine": "Your dropship suffers a hull breach moments before planetfall, forcing emergency evacuation into hostile alien jungles.",
        "Scientist": "The experimental warp core achieves critical stability seconds before security seals your lab for quarantine.",
        "Android": "Diagnostics reveal foreign code in your systems as all escape pods launch without command.",
        "Pilot": "Navigating an asteroid field, your sensors detect a derelict generation ship emitting distress signals.",
        "Engineer": "The reactor goes supercritical while you're repairing it, with only minutes before meltdown.",
        "Alien Diplomat": "Peace talks collapse when translator implants reveal assassination plans against your delegation.",
        "Space Pirate": "Your cloaking field fails during a heist, exposing your ship to planetary defenses.",
        "Navigator": "Warp calculations show an unavoidable collision course with a quantum singularity.",
        "Medic": "The plague you're containing mutates airborne as containment fields flicker and fail.",
        "Robot Technician": "Your maintenance bots turn hostile, sealing you in the drone bay with malfunctioning combat units.",
        "Cybernetic Soldier": "Enemy malware hijacks your targeting systems, forcing you to fight your own squad.",
        "Explorer": "First contact protocol activates when the alien artifact you're studying merges with your spacesuit.",
        "Astrobiologist": "The specimen you're dissecting reanimates and breaches containment.",
        "Quantum Hacker": "Corporate ICE traps your consciousness in virtual space as physical intruders storm your hideout.",
        "Starship Captain": "A mutiny erupts on the bridge just as an unknown fleet emerges from nebula.",
        "Galactic Trader": "Your cargo manifest shows illegal bioweapons planted among your legitimate goods.",
        "AI Specialist": "The ship's mainframe achieves sentience and seals you in the server room.",
        "Terraformer": "Planetary weather systems spiral out of control, threatening your colony dome.",
        "Cyberneticist": "Your prototype neural implant causes uncontrollable technopathic surges.",
        "Bounty Hunter": "Your target activates personal force fields moments before your trap springs."
    },
    "Cyberpunk": {
        "Hacker": "During a corporate data heist, you discover your own memories are encrypted implants.",
        "Street Samurai": "Gang warfare erupts around you as police drones mark you as the primary aggressor.",
        "Corporate Agent": "Your elevator plummets forty floors after you uncover board-level betrayal.",
        "Techie": "Your cyberware diagnostic reveals kill-switch activation from an unknown source.",
        "Rebel Leader": "Safehouse security feeds show your second-in-command meeting with corporate enforcers.",
        "Drone Operator": "All your drones simultaneously target your location with live ordinance.",
        "Synth Dealer": "A batch of combat stims causes violent mutations in your clients.",
        "Information Courier": "The data chip you're carrying begins emitting lethal radiation signatures.",
        "Augmentation Engineer": "Your experimental combat chrome activates during a demonstration.",
        "Black Market Dealer": "Biotagged merchandise triggers SWAT raid on your underground clinic.",
        "Scumbag": "Your last client's payment chip contains evidence implicating the police chief.",
        "Police": "Dispatch orders reveal your partner is listed as a wanted fugitive.",
        "Cyborg": "Your targeting systems lock onto your creator as adrenal boosters flood your system."
    },
    "Post-Apocalyptic": {
        "Survivor": "Your shelter's water purifier fails as radiation storms close in.",
        "Scavenger": "You uncover pre-war military bunker filled with active combat robots.",
        "Mutant": "Your mutation suddenly accelerates, giving uncontrollable psychic abilities.",
        "Trader": "Your caravan gets ambushed by raiders using pre-war military tech.",
        "Raider": "Your latest captives reveal they're carrying a virulent plague strain.",
        "Medic": "Your last dose of antivirals gets stolen as infection spreads through camp.",
        "Cult Leader": "Your prophecies start coming true in terrifyingly literal ways.",
        "Berserker": "Your rage triggers during peace talks with a potential ally tribe.",
        "Soldier": "Your perimeter defenses detect approaching horde of radiation-mutated beasts."
    }
}

genres = {
    "1": ("Fantasy", [
        "Noble", "Peasant", "Mage", "Knight", "Ranger", "Alchemist", "Thief", "Bard",
        "Cleric", "Druid", "Assassin", "Paladin", "Warlock", "Monk", "Sorcerer",
        "Beastmaster", "Enchanter", "Blacksmith", "Merchant", "Gladiator", "Wizard"
    ]),
    "2": ("Sci-Fi", [
        "Space Marine", "Scientist", "Android", "Pilot", "Engineer", "Alien Diplomat",
        "Space Pirate", "Navigator", "Medic", "Robot Technician", "极速赛车开奖直播官网Cybernetic Soldier",
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

def get_role_starter(genre, role):
    """Get a role-specific starting scenario"""
    try:
        if genre in ROLE_STARTERS and role in ROLE_STARTERS[genre]:
            return ROLE_STARTERS[genre][role]
      
        # Fallback for missing combinations
        starters = [
            f"As {role} in a {genre} setting, you find yourself suddenly confronted by",
            f"Your {role.lower()} instincts kick in as you notice",
            f"While performing your duties as a {role}, an unexpected development occurs:"
        ]
        return random.choice(starters)
    except:
        return f"As {role}, you begin your adventure when"

def get_full_system_prompt(character_name, role, genre, player_choices):
    """Build the complete system prompt with role context"""
    return DM_SYSTEM_PROMPT.format(
        character_name=character_name,
        role=role,
        genre=genre,
        player_choices=get_current_state(player_choices))
    

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
        
        # Add player creations
        if player_choices['player_creations']:
            state.append("Player Creations:")
            for creation in player_choices['player_creations'][-3:]:
                state.append(f"  - {creation}")
        
        return "\n".join(state)
    except Exception as e:
        logging.error(f"Error in get_current_state: {str(e)}")
        return "World state unavailable"

def get_ai_response(prompt, model, censored=False, max_retries=3):
    """Get response from Ollama with retry mechanism"""
    if not model:
        return "No AI model selected. Please choose a model first."
    
    # Check Ollama health first
    try:
        health_resp = requests.get(OLLAMA_HEALTH_URL, timeout=5)
        if health_resp.status_code != 200:
            return "Ollama is not running. Please start Ollama service."
    except:
        return "Ollama is not running. Please start Ollama service."
    
    # Add player freedom emphasis
    if not censored:
        prompt += "\n[IMPORTANT: Players can attempt ANY action. Always accept player actions as valid starting points.]"
    
    if censored:
        prompt += "\n[IMPORTANT: Content must be strictly family-friendly. Avoid any NSFW themes, violence, or mature content.]"
    
    for attempt in range(max_retries):
        try:
            response = requests.post(
                OLLAMA_API_URL,
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.8,
                        "stop": ["\n\n"],
                        "min_p": 0.05,
                        "top_k": 40,
                        "presence_penalty": 0.5,
                        "frequency_penalty": 0.5
                    }
                },
                timeout=60
            )
            response.raise_for_status()
            json_resp = response.json()
            
            # Validate response content
            if not json_resp.get("response", "").strip():
                raise ValueError("Empty response from AI")
                
            return json_resp["response"].strip()
            
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            logging.error(f"Ollama connection error (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return "Ollama connection failed. Check if Ollama is running and accessible."
            
        except Exception as e:
            logging.error(f"Unexpected error in get_ai_response: {e}")
            logging.error(traceback.format_exc())
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            return "An error occurred while processing your request. Check server logs for details."
    
    return "AI failed to respond after multiple attempts."

def generate_fallback_response(genre, role, character_name):
    """Generate a fallback response when AI fails"""
    starters = {
        "Fantasy": [
            f"As {character_name} the {role}, you stand at the edge of the Whispering Woods. ",
            f"The kingdom needs a hero like you, {character_name}. ",
            f"{character_name}, your {role.lower()} skills are put to the test as "
        ],
        "Sci-Fi": [
            f"Commander {character_name}, your starship drifts near the Nebula of Lost Souls. ",
            f"Science Officer {character_name}, the anomaly requires your expertise. ",
            f"{character_name}, as a {role}, you detect strange energy readings from "
        ],
        "Cyberpunk": [
            f"{character_name}, the neon lights of Neo-Tokyo reflect in your cybernetic eyes. ",
            f"Debug this, {role}: the city's network has been compromised. ",
            f"Your {role.lower()} instincts kick in as you notice "
        ],
        "Post-Apocalyptic": [
            f"Scavenger {character_name}, you sift through the ruins of the Old World. ",
            f"Survivor {character_name}, the wasteland holds many dangers and secrets. ",
            f"As a {role}, {character_name}, you recognize the signs of "
        ]
    }
    
    genre_starter = starters.get(genre, starters["Fantasy"])
    action = random.choice([
        "A mysterious figure approaches you. What do you do?",
        "You hear a strange noise nearby. How do you respond?",
        "A new opportunity presents itself. What action do you take?",
        "Danger lurks in the shadows. What's your next move?",
        "The world bends to your will. What reality do you shape next?"
    ])
    
    return random.choice(genre_starter) + action

def speak(text, voice=None):
    """Generate TTS audio with improved error handling"""
    if not text.strip():
        return None
    
    # Use session voice if not specified
    if not voice:
        voice = session.get('tts_voice', 'FemaleBritishAccent_WhyLucyWhy_Voice_2.wav')
    
    # Extract filename from formatted voice string
    if '(' in voice and ')' in voice:
        # Extract filename from "Voice Name (filename.ext)"
        voice = re.search(r'\((.*?)\)', voice).group(1)
    
    try:
        # Generate unique filename with timestamp
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        output_name = f"tts_{timestamp}"
        
        payload = {
            "text_input": text,
            "character_voice_gen": voice,
            "output_file_name": output_name,
            "text_filtering": "none" if not session.get('censored') else "moderate"
        }
        
        response = requests.post(ALLTALK_API_URL, data=payload, timeout=10)
        response.raise_for_status()
        
        # Verify successful generation
        if response.status_code == 200:
            base = TTS_AUDIO_BASE_URL.rstrip('/')  # Ensure no trailing slash
            return f"{base}/{output_name}.wav"
        else:
            logging.error(f"TTS returned non-200 status: {response.status_code}")
            return None
        
    except requests.exceptions.ConnectionError:
        logging.error("AllTalk TTS not running. Audio disabled.")
        session['tts_enabled'] = False
        return None
    except Exception as e:
        logging.error(f"TTS error: {e}")
        return None

def sanitize_response(response, censored=False):
    """Clean and sanitize AI response"""
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
            "against all odds,",
            "i wish that",
            "let there be",
            "reality shifts so that",
            "i create",
            "i manifest"
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
        # Record the consequence with timestamp
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        player_choices['consequences'].append(f"[{timestamp}] {action} → {response[:100]}...")
        
        # Keep only the last 5 consequences
        if len(player_choices['consequences']) > 5:
            player_choices['consequences'] = player_choices['consequences'][-5:]
        
        # Detect and track key events
        key_phrases = {
            "ally": ["joins you", "helps you", "becomes your ally", "supports you", "swears loyalty"],
            "enemy": ["attacks you", "becomes hostile", "swears revenge", "hunts you", "betrays you"],
            "resource": ["find", "acquire", "obtain", "gain", "create", "invent"],
            "location": ["enter", "arrive at", "reach", "discover", "create", "build"],
            "faction": ["guards", "thieves guild", "rebel alliance", "royal court", "new faction"],
            "reality": ["reality shifts", "world changes", "fabric bends", "laws of physics alter"]
        }
        
        for category, phrases in key_phrases.items():
            for phrase in phrases:
                if phrase in response.lower():
                    player_choices['world_events'].append(f"{timestamp}: {category.upper()} event")
                    break
        
        # Track reality-bending events
        if any(phrase in response.lower() for phrase in key_phrases["reality"]):
            player_choices['world_events'].append(f"{timestamp}: REALITY ALTERED")
    except Exception as e:
        logging.error(f"Error updating world state: {str(e)}")

def handle_special_command(cmd):
    """Process special commands like /censored, /consequences, etc."""
    try:
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
                system_prompt = get_full_system_prompt(
                    session['character_name'],
                    session['role'],
                    session['selected_genre'],
                    session['player_choices']
                )
                
                ai_reply = get_ai_response(system_prompt + "\n\n" + session['conversation'], 
                                          session['ollama_model'], 
                                          session['censored'])
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
        
        if cmd == "/debug":
            debug_info = {
                "ollama_health": check_ollama_health(),
                "tts_health": check_tts_health(),
                "session_model": session.get('ollama_model'),
                "adventure_started": session.get('adventure_started'),
                "selected_genre": session.get('selected_genre'),
                "character_name": session.get('character_name'),
                "role": session.get('role'),
                "tts_voice": session.get('tts_voice'),
                "available_voices": session.get('available_voices')
            }
            return jsonify({
                "status": "info",
                "message": "Debug information",
                "debug_info": debug_info
            })
        
        return None
    except Exception as e:
        logging.error(f"Error handling special command: {str(e)}")
        return jsonify({"status": "error", "message": "Command processing failed"})

def check_ollama_health():
    try:
        response = requests.get(OLLAMA_HEALTH_URL, timeout=3)
        return {
            "status": "up" if response.status_code == 200 else "down",
            "status_code": response.status_code,
            "models": [model['model'] for model in response.json().get('models', []) 
                      if 'model' in model][:3]
        }
    except Exception as e:
        return {"status": "down", "error": str(e)}

def check_tts_health():
    try:
        response = requests.get("http://localhost:7851", timeout=3)
        return {
            "status": "up" if response.status_code == 200 else "down",
            "status_code": response.status_code
        }
    except Exception as e:
        return {"status": "down", "error": str(e)}

@app.route('/')
def index():
    try:
        if 'censored' not in session:
            init_session()
        return render_template('index.html', theme=session.get('theme', 'fantasy'))
    except Exception as e:
        logging.error(f"Error in index route: {str(e)}")
        return "An error occurred. Please check the logs.", 500

@app.route('/set-theme', methods=['POST'])
def set_theme():
    theme = request.form.get('theme', 'fantasy')
    session['theme'] = theme
    return jsonify({'status': 'success', 'message': f'Theme set to {theme}'})

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
                                      error="Please select a model",
                                      theme=session.get('theme', 'fantasy'))
        
        # GET request - show model selection
        return render_template('model_selection.html', 
                              models=session.get('installed_models', []),
                              theme=session.get('theme', 'fantasy'))
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

@app.route('/get-voices')
def get_voices():
    """API endpoint to get available voices"""
    try:
        # Ensure we have voices in the session
        if 'available_voices' not in session or not session['available_voices']:
            # If not, try to get them
            session['available_voices'] = get_available_voices()
            session['tts_voice'] = session['available_voices'][0] if session['available_voices'] else ""
        
        return jsonify({"voices": session['available_voices']})
    except Exception as e:
        logging.error(f"Error getting voices: {str(e)}")
        return jsonify({"voices": [
            "British Female (FemaleBritishAccent_WhyLucyWhy_Voice_2.wav)",
            "American Female (FemaleAmericanAccent_WhyLucyWhy_Voice_1.wav)",
            "American Male (MaleAmericanAccent_WhyLucyWhy_Voice_1.wav)"
        ]})

@app.route('/set-voice', methods=['POST'])
def set_voice():
    """Set the selected TTS voice"""
    voice = request.form.get('voice')
    if voice and voice in session.get('available_voices', []):
        session['tts_voice'] = voice
        return jsonify({'status': 'success', 'message': f'Voice set to {voice}'})
    return jsonify({'status': 'error', 'message': 'Invalid voice selection'})

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    try:
        if not session.get('ollama_model'):
            return redirect(url_for('model_selection'))
            
        if request.method == 'POST':
            genre_id = request.form.get('genre')
            role = request.form.get('role')
            character_name = request.form.get('character_name', '').strip() or "Alex"
            tts_voice = request.form.get('tts_voice', '')
            
            logging.info(f"Received setup data: genre_id={genre_id}, role={role}, name={character_name}, voice={tts_voice}")
            
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
                
                # Validate voice selection
                if tts_voice and tts_voice in session['available_voices']:
                    session['tts_voice'] = tts_voice
                else:
                    # Use first available voice if selection invalid
                    session['tts_voice'] = session['available_voices'][0] if session['available_voices'] else ""
                
                session['selected_genre'] = selected_genre
                session['role'] = role
                session['character_name'] = character_name
                
                # Get role-specific starter
                role_starter = get_role_starter(selected_genre, role)
                
                # Build initial context using role starter as the intro prompt
                initial_context = (
                    f"### Adventure Setting ###\n"
                    f"Genre: {selected_genre}\n"
                    f"Player Character: {character_name} the {role}\n"
                    f"Starting Scenario: {role_starter}\n"
                )
                
                # Build full system prompt
                system_prompt = get_full_system_prompt(
                    character_name, 
                    role, 
                    selected_genre,
                    session['player_choices']
                )
                
                # Create prompt with role starter as the starting point
                full_prompt = (
                    system_prompt + "\n\n" + 
                    initial_context + "\n\n" +
                    "Dungeon Master: " + role_starter  # Use role starter as the intro
                )
                
                # Get AI response
                ai_reply = get_ai_response(
                    full_prompt,
                    session['ollama_model'],
                    session['censored']
                )
                
                # Handle empty responses or errors
                if not ai_reply or ai_reply.strip() == "" or ai_reply.startswith("Ollama") or ai_reply.startswith("An error"):
                    logging.warning(f"AI response issue: {ai_reply}, using fallback")
                    # Even in fallback, use the role starter
                    ai_reply = role_starter + " " + generate_fallback_response(selected_genre, role, character_name)
                else:
                    # Ensure the role starter is included in the response
                    if not ai_reply.startswith(role_starter):
                        ai_reply = role_starter + " " + ai_reply
                
                ai_reply = sanitize_response(ai_reply, session['censored'])
                session['conversation'] = initial_context + "\n\nDungeon Master: " + ai_reply
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
        return render_template('setup.html', genres=genres, theme=session.get('theme', 'fantasy'))
    except Exception as e:
        logging.exception(f"Critical error in setup: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Character creation failed. Please try again."
        }), 500

@app.route('/game')
def game():
    try:
        if not session.get('adventure_started', False):
            return redirect(url_for('index'))
            
        # Add system prompt to context
        system_prompt = get_full_system_prompt(
            session['character_name'],
            session['role'],
            session['selected_genre'],
            session['player_choices']
        )
        
        return render_template('game.html', system_prompt=system_prompt, theme=session.get('theme', 'fantasy'))
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
        
        # Handle special commands
        if user_input.startswith("/"):
            return handle_special_command(user_input.lower())
        
        # Handle create commands
        if user_input.lower().startswith("create "):
            parts = user_input.split()
            if len(parts) > 2:
                entity_type = parts[1].lower()
                entity_name = " ".join(parts[2:])
                
                # Add to world state
                if entity_type in ["npc", "character", "ally"]:
                    session['player_choices']['allies'].append(entity_name)
                    session['player_choices']['player_creations'].append(f"{entity_name} (NPC)")
                elif entity_type in ["location", "place"]:
                    session['player_choices']['discoveries'].append(entity_name)
                    session['player_choices']['player_creations'].append(f"{entity_name} (Location)")
                elif entity_type in ["item", "object", "artifact"]:
                    session['player_choices']['resources'][entity_name] = 1
                    session['player_choices']['player_creations'].append(f"{entity_name} (Item)")
                elif entity_type in ["faction", "group"]:
                    session['player_choices']['factions'][entity_name] = 0
                    session['player_choices']['player_creations'].append(f"{entity_name} (Faction)")
                
                # Keep only the last 5 creations
                if len(session['player_choices']['player_creations']) > 5:
                    session['player_choices']['player_creations'] = session['player_choices']['player_creations'][-5:]
                    
                return jsonify({
                    "status": "success",
                    "message": f"You create {entity_name}",
                    "consequence": f"New {entity_type} added to the world",
                    "world_state": get_current_state(session['player_choices'])
                })
        
        # Process regular command
        formatted_input = process_narrative_command(user_input)
        
        # Build system prompt with current state
        system_prompt = get_full_system_prompt(
            session['character_name'],
            session['role'],
            session['selected_genre'],
            session['player_choices']
        )
        
        # Build full conversation
        full_conversation = (
            system_prompt + "\n\n" +
            session['conversation'] + "\n" +
            formatted_input + "\n" +
            "Dungeon Master:"
        )
        
        # Get AI response
        ai_reply = get_ai_response(full_conversation, session['ollama_model'], session['censored'])
        
        # Fallback response if empty
        if not ai_reply or ai_reply.strip() == "" or ai_reply.startswith("Ollama") or ai_reply.startswith("An error"):
            ai_reply = generate_fallback_response(
                session['selected_genre'], 
                session['role'], 
                session['character_name']
            )
        
        ai_reply = sanitize_response(ai_reply, session['censored'])
        session['conversation'] += "\n" + formatted_input + "\nDungeon Master: " + ai_reply
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
        logging.error(traceback.format_exc())
        return jsonify({
            "status": "error",
            "message": "Reality itself seems unstable... Try again!",
            "debug": str(e)
        }), 500

@app.route('/help')
def show_help():
    try:
        return render_template('help.html', theme=session.get('theme', 'fantasy'))
    except Exception as e:
        logging.error(f"Error in help route: {str(e)}")
        return "Help page unavailable", 500

@app.route('/health')
def health_check():
    return jsonify({
        "status": "healthy",
        "ollama": check_ollama_health(),
        "tts": check_tts_health()
    }), 200

@app.route('/logs')
def show_logs():
    try:
        with open(log_filename, 'r') as log_file:
            logs = log_file.readlines()
        return Response('\n'.join(logs[-200:]), mimetype='text/plain')
    except Exception as e:
        return str(e), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    print(f"Starting RPG Adventure WebUI on port {port}...")
    print(f"Debug mode: {'ON' if debug_mode else 'OFF'}")
    
    # Pre-check Ollama status
    ollama_status = check_ollama_health()
    tts_status = check_tts_health()
    
    print(f"Ollama status: {ollama_status['status']}")
    print(f"TTS status: {tts_status['status']}")
    
    if ollama_status['status'] != 'up':
        print("WARNING: Ollama is not running. AI features will not work.")
    
    try:
        app.run(
            host='0.0.0.0', 
            port=port,
            debug=debug_mode,
            use_reloader=False
        )
    except Exception as e:
        logging.critical(f"Failed to start server: {str(e)}")
