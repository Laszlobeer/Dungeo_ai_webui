document.addEventListener('DOMContentLoaded', function() {
    // Setup page functionality
    if (document.getElementById('character-form')) {
        const genreSelect = document.getElementById('genre');
        const roleSelect = document.getElementById('role');
        const form = document.getElementById('character-form');
        const loading = document.getElementById('loading');
        const startMessage = document.getElementById('start-message');
        
        // Update roles when genre changes
        genreSelect.addEventListener('change', function() {
            const genreId = this.value;
            fetch(`/get-roles?genre=${genreId}`)
                .then(response => response.json())
                .then(data => {
                    roleSelect.innerHTML = '';
                    data.roles.forEach((role, index) => {
                        const option = document.createElement('option');
                        option.value = role;
                        option.textContent = role;
                        roleSelect.appendChild(option);
                    });
                });
        });
        
        // Form submission
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const formData = new FormData(this);
            loading.classList.remove('hidden');
            
            fetch('/setup', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                loading.classList.add('hidden');
                if (data.status === 'success') {
                    window.location.href = '/game';
                } else {
                    startMessage.textContent = data.message || 'Error starting adventure';
                    startMessage.classList.remove('hidden');
                }
            })
            .catch(error => {
                loading.classList.add('hidden');
                startMessage.textContent = 'Error starting adventure';
                startMessage.classList.remove('hidden');
                console.error('Error:', error);
            });
        });
    }
    
    // Game page functionality
    if (document.getElementById('command-input')) {
        const commandInput = document.getElementById('command-input');
        const submitBtn = document.getElementById('submit-btn');
        const conversationDiv = document.getElementById('conversation');
        const consequenceText = document.getElementById('consequence-text');
        const worldStateContent = document.getElementById('world-state-content');
        const ttsPlayer = document.getElementById('tts-player');
        const censoredBtn = document.getElementById('censored-btn');
        const redoBtn = document.getElementById('redo-btn');
        const saveBtn = document.getElementById('save-btn');
        const consequencesBtn = document.getElementById('consequences-btn');
        const helpBtn = document.getElementById('help-btn');
        
        // Add initial DM message
        addMessage('dm', 'Welcome to your adventure!');
        
        // Submit command
        function submitCommand() {
            const command = commandInput.value.trim();
            if (!command) return;
            
            commandInput.value = '';
            
            // Add player message to conversation
            addMessage('player', command);
            
            // Send command to server
            fetch('/command', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `command=${encodeURIComponent(command)}`
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    // Add DM response
                    addMessage('dm', data.message);
                    
                    // Update consequence display
                    consequenceText.textContent = data.consequence;
                    
                    // Update world state
                    if (data.world_state) {
                        worldStateContent.innerHTML = data.world_state.replace(/\n/g, '<br>');
                    }
                    
                    // Play TTS if available
                    if (data.audio_url) {
                        ttsPlayer.src = data.audio_url;
                        ttsPlayer.classList.remove('hidden');
                        ttsPlayer.play();
                    }
                } else {
                    addMessage('system', data.message || 'Error processing command');
                }
            })
            .catch(error => {
                addMessage('system', 'Error processing command');
                console.error('Error:', error);
            });
        }
        
        submitBtn.addEventListener('click', submitCommand);
        commandInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                submitCommand();
            }
        });
        
        // Add message to conversation
        function addMessage(speaker, text) {
            const messageDiv = document.createElement('div');
            messageDiv.classList.add('message', speaker);
            
            const speakerSpan = document.createElement('div');
            speakerSpan.classList.add('speaker');
            speakerSpan.textContent = speaker === 'dm' ? 'Dungeon Master' : 'You';
            
            const textDiv = document.createElement('div');
            textDiv.classList.add('text');
            textDiv.textContent = text;
            
            messageDiv.appendChild(speakerSpan);
            messageDiv.appendChild(textDiv);
            conversationDiv.appendChild(messageDiv);
            
            // Scroll to bottom
            conversationDiv.scrollTop = conversationDiv.scrollHeight;
        }
        
        // Button handlers
        censoredBtn.addEventListener('click', function() {
            fetch('/command', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: 'command=/censored'
            })
            .then(response => response.json())
            .then(data => {
                addMessage('system', data.message);
            });
        });
        
        redoBtn.addEventListener('click', function() {
            fetch('/command', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: 'command=/redo'
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    // Remove last DM message and add new one
                    const dmMessages = document.querySelectorAll('.message.dm');
                    if (dmMessages.length > 0) {
                        dmMessages[dmMessages.length - 1].remove();
                    }
                    addMessage('dm', data.message);
                    
                    // Play TTS if available
                    if (data.audio_url) {
                        ttsPlayer.src = data.audio_url;
                        ttsPlayer.classList.remove('hidden');
                        ttsPlayer.play();
                    }
                } else {
                    addMessage('system', data.message);
                }
            });
        });
        
        saveBtn.addEventListener('click', function() {
            fetch('/command', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: 'command=/save'
            })
            .then(response => response.json())
            .then(data => {
                addMessage('system', data.message);
            });
        });
        
        consequencesBtn.addEventListener('click', function() {
            fetch('/command', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: 'command=/consequences'
            })
            .then(response => response.json())
            .then(data => {
                addMessage('system', data.message);
            });
        });
        
        helpBtn.addEventListener('click', function() {
            window.location.href = '/help';
        });
    }
});