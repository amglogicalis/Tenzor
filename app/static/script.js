// ⚙️ Configuración del estado global
let state = {
    chats: [],                 // Array de chats: { id, title, messages: [{ role, content, images }] }
    activeChatId: null,        // ID del chat seleccionado
    userApiKey: "",            // Clave del cliente configurada en Ajustes (localStorage)
    theme: "dark",             // Tema actual: "dark" u "light"
    chatIdBeingRenamed: null,  // ID del chat que se está renombrando actualmente
    attachments: [],           // Archivos adjuntos en espera: { name, type, content, isImage }
    selectedModel: "tenz-1-nova" // Modelo de IA seleccionado actualmente (Nova por defecto)
};


// 🗺️ Selectores DOM
const sidebar = document.getElementById("sidebar");
const sidebarToggle = document.getElementById("sidebar-toggle");
const newChatBtn = document.getElementById("new-chat-btn");
const chatList = document.getElementById("chat-list");
const currentChatTitle = document.getElementById("current-chat-title");
const messagesContainer = document.getElementById("messages-container");
const chatInput = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");
const attachBtn = document.getElementById("attach-btn");
const chatFileInput = document.getElementById("chat-file-input");
const attachmentPreview = document.getElementById("attachment-preview");
const chatArea = document.querySelector(".chat-area");
const modelSelector = document.getElementById("model-selector");

// Selectores GPU Lifecycle
const gpuStatusContainer = document.getElementById("gpu-status-container");
const gpuStatusBadge = document.getElementById("gpu-status-badge");
const gpuProgressWrapper = document.getElementById("gpu-progress-wrapper");
const gpuProgressBarFill = document.getElementById("gpu-progress-bar-fill");
const gpuProgressText = document.getElementById("gpu-progress-text");
const gpuWakeBtn = document.getElementById("gpu-wake-btn");
const gpuSleepBtn = document.getElementById("gpu-sleep-btn");

let gpuPollingInterval = null;
let gpuProgressInterval = null;
let gpuProgressValue = 0;

// Selector Ajustes Modal
const settingsBtn = document.getElementById("settings-btn");
const settingsModal = document.getElementById("settings-modal");
const closeSettingsModalBtn = document.getElementById("close-settings-modal-btn");
const cancelSettingsBtn = document.getElementById("cancel-settings-btn");
const saveSettingsBtn = document.getElementById("save-settings-btn");
const settingsApiKeyInput = document.getElementById("settings-api-key");
const settingsThemeSelect = document.getElementById("settings-theme");

// Selector Renombrar Modal
const renameModal = document.getElementById("rename-modal");
const renameChatInput = document.getElementById("rename-chat-input");
const closeRenameModalBtn = document.getElementById("close-rename-modal-btn");
const cancelRenameBtn = document.getElementById("cancel-rename-btn");
const saveRenameBtn = document.getElementById("save-rename-btn");

const welcomeScreen = document.getElementById("welcome-screen");

// 🚀 Inicialización de la Aplicación
document.addEventListener("DOMContentLoaded", async () => {
    // 1. Cargar ajustes guardados en localStorage
    state.userApiKey = localStorage.getItem("tenzor_user_api_key") || "";
    settingsApiKeyInput.value = state.userApiKey;

    // 2. Cargar tema visual guardado
    state.theme = localStorage.getItem("tenzor_theme") || "dark";
    applyTheme(state.theme);
    settingsThemeSelect.value = state.theme;

    // 3. Cargar chats guardados
    loadChatsFromStorage();

    // 4. Registrar Event Listeners
    setupEventListeners();

    // 5. Renderizar interfaz inicial
    renderChatList();
    if (state.chats.length > 0) {
        selectChat(state.chats[0].id);
    } else {
        showWelcomeScreen();
    }

    // 6. Inicializar modelo seleccionado y estado GPU
    state.selectedModel = modelSelector.value;
    handleModelSelectionChange();
});




// 💾 Gestión del almacenamiento local (localStorage)
function loadChatsFromStorage() {
    const saved = localStorage.getItem("tenzor_chats");
    if (saved) {
        try {
            state.chats = JSON.parse(saved);
        } catch (e) {
            state.chats = [];
        }
    }
}

function saveChatsToStorage() {
    localStorage.setItem("tenzor_chats", JSON.stringify(state.chats));
}

// 🌓 Lógica de Tema Visual (Claro / Oscuro)
function applyTheme(theme) {
    if (theme === "light") {
        document.body.classList.add("light-theme");
    } else {
        document.body.classList.remove("light-theme");
    }
}

// 🎛️ Registrar Event Listeners
function setupEventListeners() {
    // Alternar sidebar en móvil
    sidebarToggle.addEventListener("click", () => sidebar.classList.toggle("open"));
    
    // Cerrar sidebar si se hace clic fuera en móvil
    document.addEventListener("click", (e) => {
        if (window.innerWidth <= 768 && !sidebar.contains(e.target) && e.target !== sidebarToggle && !sidebarToggle.contains(e.target)) {
            sidebar.classList.remove("open");
        }
    });

    // Crear nuevo chat
    newChatBtn.addEventListener("click", () => {
        createNewChat();
        if (window.innerWidth <= 768) sidebar.classList.remove("open");
    });

    // Auto-crecimiento de Textarea de entrada de texto
    chatInput.addEventListener("input", () => {
        chatInput.style.height = "auto";
        chatInput.style.height = (chatInput.scrollHeight) + "px";
        updateSendButtonState();
    });

    // Abrir selector de archivos
    attachBtn.addEventListener("click", () => {
        chatFileInput.click();
    });

    // Procesar archivos seleccionados
    chatFileInput.addEventListener("change", (e) => {
        handleFilesSelect(e.target.files);
        chatFileInput.value = ""; // Limpiar selector
    });

    // Soporte para arrastrar archivos (Drag & Drop)
    chatArea.addEventListener("dragover", (e) => {
        e.preventDefault();
        chatArea.classList.add("drag-active");
    });

    chatArea.addEventListener("dragleave", (e) => {
        e.preventDefault();
        chatArea.classList.remove("drag-active");
    });

    chatArea.addEventListener("drop", (e) => {
        e.preventDefault();
        chatArea.classList.remove("drag-active");
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            handleFilesSelect(e.dataTransfer.files);
        }
    });

    // Cambiar de modelo de IA
    modelSelector.addEventListener("change", (e) => {
        state.selectedModel = e.target.value;
        handleModelSelectionChange();
    });

    // Ciclo de vida de la GPU (Botones de encendido/apagado)
    gpuWakeBtn.addEventListener("click", wakeGPU);
    gpuSleepBtn.addEventListener("click", sleepGPU);


    // Enviar mensaje al pulsar Enter (sin Shift)
    chatInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Enviar mensaje al pulsar botón
    sendBtn.addEventListener("click", sendMessage);

    // --- Modal de Ajustes ---
    settingsBtn.addEventListener("click", () => {
        settingsApiKeyInput.value = state.userApiKey;
        settingsThemeSelect.value = state.theme;
        settingsModal.classList.add("open");
    });
    
    const closeSettings = () => settingsModal.classList.remove("open");
    closeSettingsModalBtn.addEventListener("click", closeSettings);
    cancelSettingsBtn.addEventListener("click", closeSettings);

    saveSettingsBtn.addEventListener("click", () => {
        // Guardar API Key
        state.userApiKey = settingsApiKeyInput.value.trim();
        localStorage.setItem("tenzor_user_api_key", state.userApiKey);

        // Guardar y Aplicar Tema
        state.theme = settingsThemeSelect.value;
        localStorage.setItem("tenzor_theme", state.theme);
        applyTheme(state.theme);

        closeSettings();
    });

    // --- Modal de Renombrar Chat ---
    const closeRename = () => {
        renameModal.classList.remove("open");
        state.chatIdBeingRenamed = null;
    };
    closeRenameModalBtn.addEventListener("click", closeRename);
    cancelRenameBtn.addEventListener("click", closeRename);

    saveRenameBtn.addEventListener("click", saveChatName);
    renameChatInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            saveChatName();
        }
    });
}

// 📝 Lógica de Gestión de Chats
function createNewChat() {
    const newChat = {
        id: "chat_" + Date.now(),
        title: "Nuevo Chat " + (state.chats.length + 1),
        messages: []
    };
    state.chats.unshift(newChat);
    saveChatsToStorage();
    renderChatList();
    selectChat(newChat.id);
}

function selectChat(chatId) {
    state.activeChatId = chatId;
    renderChatList();
    
    const activeChat = state.chats.find(c => c.id === chatId);
    if (!activeChat) return;

    currentChatTitle.textContent = activeChat.title;
    
    // Limpiar contenedor de mensajes
    messagesContainer.innerHTML = "";
    
    if (activeChat.messages.length === 0) {
        showWelcomeScreen();
    } else {
        welcomeScreen.style.display = "none";
        activeChat.messages.forEach(msg => {
            appendMessageMarkup(msg.role, msg.content, msg.images);
        });
        scrollToBottom();
    }
}

function deleteChat(chatId, e) {
    if (e) e.stopPropagation();
    
    state.chats = state.chats.filter(c => c.id !== chatId);
    saveChatsToStorage();
    renderChatList();
    
    if (state.activeChatId === chatId) {
        if (state.chats.length > 0) {
            selectChat(state.chats[0].id);
        } else {
            state.activeChatId = null;
            currentChatTitle.textContent = "Nuevo Chat";
            messagesContainer.innerHTML = "";
            showWelcomeScreen();
        }
    }
}

function renameChat(chatId, e) {
    if (e) e.stopPropagation();
    
    const chat = state.chats.find(c => c.id === chatId);
    if (!chat) return;
    
    state.chatIdBeingRenamed = chatId;
    renameChatInput.value = chat.title;
    renameModal.classList.add("open");
    setTimeout(() => renameChatInput.focus(), 50);
}

function saveChatName() {
    const newTitle = renameChatInput.value.trim();
    if (newTitle && state.chatIdBeingRenamed) {
        const chat = state.chats.find(c => c.id === state.chatIdBeingRenamed);
        if (chat) {
            chat.title = newTitle;
            saveChatsToStorage();
            renderChatList();
            if (state.activeChatId === state.chatIdBeingRenamed) {
                currentChatTitle.textContent = chat.title;
            }
        }
    }
    renameModal.classList.remove("open");
    state.chatIdBeingRenamed = null;
}

// 🖥️ Renderizar Sidebar y Elementos Visuales
function renderChatList() {
    chatList.innerHTML = "";
    
    state.chats.forEach(chat => {
        const item = document.createElement("div");
        item.className = `chat-item ${chat.id === state.activeChatId ? 'active' : ''}`;
        item.addEventListener("click", () => selectChat(chat.id));
        
        item.innerHTML = `
            <i class="fa-regular fa-message chat-icon"></i>
            <span class="chat-item-title">${escapeHTML(chat.title)}</span>
            <div class="chat-item-actions">
                <button class="chat-action-btn rename-btn" title="Renombrar"><i class="fa-solid fa-pen"></i></button>
                <button class="chat-action-btn delete-btn" title="Eliminar"><i class="fa-solid fa-trash"></i></button>
            </div>
        `;
        
        // Agregar eventos de botones internos sin disparar clic de selección
        item.querySelector(".rename-btn").addEventListener("click", (e) => renameChat(chat.id, e));
        item.querySelector(".delete-btn").addEventListener("click", (e) => deleteChat(chat.id, e));
        
        chatList.appendChild(item);
    });
}

function showWelcomeScreen() {
    messagesContainer.innerHTML = "";
    messagesContainer.appendChild(welcomeScreen);
    welcomeScreen.style.display = "flex";
}

// 💬 Enviar y procesar mensajes
// 📎 Procesar selección y arrastre de archivos
function handleFilesSelect(files) {
    if (!files || files.length === 0) return;

    Array.from(files).forEach(file => {
        // Limitar tamaño a 15MB
        if (file.size > 15 * 1024 * 1024) {
            alert(`El archivo ${file.name} es demasiado grande. El límite es 15MB.`);
            return;
        }

        const isImage = file.type.startsWith("image/");
        const reader = new FileReader();

        if (isImage) {
            reader.onload = (e) => {
                state.attachments.push({
                    name: file.name,
                    type: file.type,
                    content: e.target.result, // base64 data URL
                    isImage: true
                });
                renderAttachmentsPreview();
                updateSendButtonState();
            };
            reader.readAsDataURL(file);
        } else {
            // Asumir que es archivo de texto (logs, código, etc.)
            reader.onload = (e) => {
                state.attachments.push({
                    name: file.name,
                    type: file.type,
                    content: e.target.result, // texto plano
                    isImage: false
                });
                renderAttachmentsPreview();
                updateSendButtonState();
            };
            reader.readAsText(file);
        }
    });
}

function renderAttachmentsPreview() {
    attachmentPreview.innerHTML = "";
    
    if (state.attachments.length === 0) {
        attachmentPreview.style.display = "none";
        return;
    }

    attachmentPreview.style.display = "flex";

    state.attachments.forEach((file, index) => {
        const item = document.createElement("div");
        item.className = `preview-item ${file.isImage ? 'image' : ''}`;
        
        if (file.isImage) {
            item.innerHTML = `
                <img src="${file.content}" alt="${escapeHTML(file.name)}">
                <button class="remove-btn" onclick="removeAttachment(${index})">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            `;
        } else {
            item.innerHTML = `
                <i class="fa-solid fa-file-code"></i>
                <span>${escapeHTML(file.name)}</span>
                <button class="remove-btn" onclick="removeAttachment(${index})">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            `;
        }
        
        attachmentPreview.appendChild(item);
    });
}

// Hacer la función accesible globalmente para el onclick en los botones de remove
window.removeAttachment = function(index) {
    state.attachments.splice(index, 1);
    renderAttachmentsPreview();
    updateSendButtonState();
};

function updateSendButtonState() {
    sendBtn.disabled = chatInput.value.trim() === "" && state.attachments.length === 0;
}

function getFileExtension(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    const map = {
        'py': 'python',
        'js': 'javascript',
        'ts': 'typescript',
        'json': 'json',
        'html': 'html',
        'css': 'css',
        'sh': 'bash',
        'bash': 'bash',
        'yml': 'yaml',
        'yaml': 'yaml',
        'md': 'markdown',
        'log': 'log',
        'csv': 'csv'
    };
    return map[ext] || 'text';
}

// 💬 Enviar y procesar mensajes
async function sendMessage() {
    const text = chatInput.value.trim();
    const attachments = [...state.attachments];
    
    if (!text && attachments.length === 0) return;

    // Si no hay un chat activo, crearlo
    if (!state.activeChatId) {
        createNewChat();
    }

    const activeChat = state.chats.find(c => c.id === state.activeChatId);
    if (!activeChat) return;

    // Limpiar input y previsualización
    chatInput.value = "";
    chatInput.style.height = "auto";
    state.attachments = [];
    renderAttachmentsPreview();
    sendBtn.disabled = true;

    // Ocultar pantalla de bienvenida
    welcomeScreen.style.display = "none";

    // 1. Procesar archivos de texto para inyectarlos en el contenido del mensaje
    let fullText = text;
    const textFiles = attachments.filter(a => !a.isImage);
    if (textFiles.length > 0) {
        textFiles.forEach(file => {
            // Añadir salto de línea y código markdown formateado
            fullText += `\n\n---\n📄 **Archivo adjunto: ${file.name}**\n\`\`\`${getFileExtension(file.name)}\n${file.content}\n\`\`\``;
        });
    }

    // 2. Procesar imágenes para enviarlas en el campo images
    const images = attachments.filter(a => a.isImage).map(a => a.content);

    // 3. Agregar y mostrar mensaje del usuario en el estado local
    const userMessage = { role: "user", content: fullText };
    if (images.length > 0) {
        userMessage.images = images;
    }
    
    activeChat.messages.push(userMessage);
    appendMessageMarkup("user", fullText, images);
    scrollToBottom();

    // 4. Si el título del chat es el genérico inicial, renombrarlo automáticamente con las primeras palabras
    if (activeChat.title.startsWith("Nuevo Chat ")) {
        const displayTitle = text || (textFiles.length > 0 ? textFiles[0].name : "Archivo Adjunto");
        activeChat.title = displayTitle.length > 25 ? displayTitle.substring(0, 22) + "..." : displayTitle;
        renderChatList();
    }

    // Guardar estado local
    saveChatsToStorage();

    // 5. Crear contenedor y animación de carga para la respuesta del asistente
    const typingIndicator = appendTypingIndicator();
    scrollToBottom();

    // 6. Obtener clave de autorización a enviar
    const apiKeyToSend = state.userApiKey;
    if (!apiKeyToSend) {
        removeTypingIndicator(typingIndicator);
        appendMessageMarkup("assistant", "⚠️ No has configurado tu API Key de Tenzor. Entra en **Ajustes** (icono de engranaje) y pégala en el campo correspondiente.");
        scrollToBottom();
        return;
    }

    // 7. Enviar petición HTTP al Backend
    try {
        const response = await fetch("/v1/chat/completions", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${apiKeyToSend}`
            },
            body: JSON.stringify({
                model: state.selectedModel,
                messages: activeChat.messages.map(m => ({
                    role: m.role,
                    content: m.content,
                    images: m.images || null
                })),
                temperature: 0.7
            })
        });

        removeTypingIndicator(typingIndicator);

        if (response.ok) {
            const data = await response.json();
            const replyText = data.choices[0].message.content;
            
            // Agregar mensaje del asistente al estado
            const assistantMessage = { role: "assistant", content: replyText };
            activeChat.messages.push(assistantMessage);
            saveChatsToStorage();

            // Mostrar el mensaje renderizando Markdown y Highlight de código
            appendMessageMarkup("assistant", replyText);
        } else {
            // Manejo de errores HTTP
            let errorText = "Ocurrió un error procesando tu consulta.";
            try {
                const errData = await response.json();
                errorText = errData.detail || errorText;
            } catch (e) {}
            
            appendMessageMarkup("assistant", `❌ Error (${response.status}): ${errorText}`);
        }
    } catch (e) {
        removeTypingIndicator(typingIndicator);
        appendMessageMarkup("assistant", `❌ Error de Red: No se pudo conectar al servidor de Tenzor API.`);
    }

    scrollToBottom();
}

// 📦 Renderizadores de Mensajes en el DOM
function appendMessageMarkup(role, content, images = []) {
    const row = document.createElement("div");
    row.className = `message-row ${role}`;

    const contentDiv = document.createElement("div");
    contentDiv.className = "message-content";

    // Crear Avatar
    const avatar = document.createElement("div");
    avatar.className = "message-avatar";
    if (role === "user") {
        avatar.innerHTML = `<i class="fa-solid fa-user"></i>`;
    } else {
        avatar.innerHTML = `<img src="/static/logo.png" alt="T" onerror="this.style.display='none'; this.parentNode.innerHTML='T'">`;
    }

    // Crear Cuerpo
    const body = document.createElement("div");
    body.className = "message-body";

    // Reemplazar la representación cruda de archivos adjuntos de texto por una pastilla (pill) visual limpia
    let displayContent = content;
    const fileAttachmentRegex = /\n\n---\n📄 \*\*Archivo adjunto: (.+?)\*\*\n\`\`\`[a-zA-Z0-9]*\n[\s\S]*?\n\`\`\`/g;
    displayContent = displayContent.replace(fileAttachmentRegex, (match, fileName) => {
        return `\n\n<div class="file-attachment-pill"><i class="fa-solid fa-file-lines"></i> ${fileName}</div>`;
    });

    // Procesamos Markdown para ambos roles
    body.innerHTML = marked.parse(displayContent);
    // Formatear código e inyectar botones de copiar
    formatAndAddCopyButtons(body);

    // Si hay imágenes asociadas a este mensaje, renderizarlas abajo
    if (images && images.length > 0) {
        const imgGrid = document.createElement("div");
        imgGrid.className = "chat-images-grid";
        imgGrid.style.display = "flex";
        imgGrid.style.flexWrap = "wrap";
        imgGrid.style.gap = "10px";
        imgGrid.style.marginTop = "12px";

        images.forEach(imgSrc => {
            const imgWrapper = document.createElement("div");
            imgWrapper.style.maxWidth = "240px";
            imgWrapper.style.maxHeight = "180px";
            imgWrapper.style.borderRadius = "8px";
            imgWrapper.style.overflow = "hidden";
            imgWrapper.style.border = "1px solid var(--border-color)";

            const img = document.createElement("img");
            img.src = imgSrc;
            img.style.width = "100%";
            img.style.height = "100%";
            img.style.objectFit = "cover";

            imgWrapper.appendChild(img);
            imgGrid.appendChild(imgWrapper);
        });

        body.appendChild(imgGrid);
    }

    contentDiv.appendChild(avatar);
    contentDiv.appendChild(body);
    row.appendChild(contentDiv);
    messagesContainer.appendChild(row);
}

function appendTypingIndicator() {
    const row = document.createElement("div");
    row.className = "message-row assistant typing-row";

    const contentDiv = document.createElement("div");
    contentDiv.className = "message-content";

    const avatar = document.createElement("div");
    avatar.className = "message-avatar";
    avatar.innerHTML = `<img src="/static/logo.png" alt="T" onerror="this.style.display='none'; this.parentNode.innerHTML='T'">`;

    const body = document.createElement("div");
    body.className = "message-body";
    body.innerHTML = `
        <div class="typing-indicator">
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
        </div>
    `;

    contentDiv.appendChild(avatar);
    contentDiv.appendChild(body);
    row.appendChild(contentDiv);
    messagesContainer.appendChild(row);
    return row;
}

function removeTypingIndicator(row) {
    if (row && row.parentNode) {
        row.parentNode.removeChild(row);
    }
}

// 💻 Formatear Código e inyectar cabecera "Copiar Código"
function formatAndAddCopyButtons(container) {
    // 1. Resaltar con Prism
    Prism.highlightAllUnder(container);

    // 2. Buscar bloques pre y añadirles cabecera
    const preBlocks = container.querySelectorAll("pre");
    preBlocks.forEach(pre => {
        // Evitar duplicados si se vuelve a renderizar
        if (pre.querySelector(".code-header")) return;

        // Obtener el lenguaje del código si existe
        const code = pre.querySelector("code");
        let lang = "código";
        if (code) {
            const classes = Array.from(code.classList);
            const langClass = classes.find(c => c.startsWith("language-"));
            if (langClass) {
                lang = langClass.replace("language-", "");
            }
        }

        // Crear la cabecera del bloque de código
        const header = document.createElement("div");
        header.className = "code-header";
        
        const langSpan = document.createElement("span");
        langSpan.className = "code-lang";
        langSpan.textContent = lang;

        const copyBtn = document.createElement("button");
        copyBtn.className = "copy-code-btn";
        copyBtn.innerHTML = `<i class="fa-regular fa-clipboard"></i> Copiar`;
        copyBtn.addEventListener("click", () => copyCodeToClipboard(pre, copyBtn));

        header.appendChild(langSpan);
        header.appendChild(copyBtn);
        
        // Insertar antes del código propiamente dicho
        pre.insertBefore(header, pre.firstChild);
    });
}

async function copyCodeToClipboard(preBlock, button) {
    const codeElement = preBlock.querySelector("code");
    if (!codeElement) return;

    // Obtener texto quitando la cabecera añadida
    const textToCopy = codeElement.innerText;

    try {
        await navigator.clipboard.writeText(textToCopy);
        button.innerHTML = `<i class="fa-solid fa-check" style="color: #10b981;"></i> ¡Copiado!`;
        setTimeout(() => {
            button.innerHTML = `<i class="fa-regular fa-clipboard"></i> Copiar`;
        }, 2000);
    } catch (e) {
        button.textContent = "Error al copiar";
    }
}

// 🧰 Helpers y Utilidades
function scrollToBottom() {
    messagesContainer.scrollTo({
        top: messagesContainer.scrollHeight,
        behavior: 'smooth'
    });
}

function escapeHTML(str) {
    return str.replace(/[&<>'"]/g, 
        tag => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            "'": '&#39;',
            '"': '&quot;'
        }[tag] || tag)
    );
}

// ==========================================================================
// ⚙️ Lógica de Ciclo de Vida de la GPU (Wake-on-Demand)
// ==========================================================================

function handleModelSelectionChange() {
    if (state.selectedModel === "tenz-1-nova") {
        gpuStatusContainer.style.display = "block";
        startGPUPolling();
    } else {
        gpuStatusContainer.style.display = "none";
        stopGPUPolling();
        enableChatUI(true);
    }
}

async function checkGPUStatus() {
    const apiKey = state.userApiKey;
    if (!apiKey) {
        updateGPUStatus("sleep");
        return;
    }

    try {
        const response = await fetch("/v1/model/status", {
            headers: {
                "Authorization": `Bearer ${apiKey}`
            }
        });
        if (response.ok) {
            const data = await response.json();
            updateGPUStatus(data.status);
        } else {
            console.error("Error al consultar el estado de la GPU:", response.statusText);
        }
    } catch (e) {
        console.error("Error de red al consultar el estado de la GPU:", e);
    }
}

function updateGPUStatus(status) {
    // Resetear clases
    gpuStatusBadge.className = "gpu-status-badge " + status;
    
    if (status === "active") {
        gpuStatusBadge.textContent = "Activo";
        gpuProgressWrapper.style.display = "none";
        gpuWakeBtn.style.display = "none";
        gpuSleepBtn.style.display = "inline-block";
        
        // Detener animación de carga si estaba corriendo
        if (gpuProgressInterval) {
            clearInterval(gpuProgressInterval);
            gpuProgressInterval = null;
        }
        
        enableChatUI(true);
    } else if (status === "waking") {
        gpuStatusBadge.textContent = "Activando";
        gpuProgressWrapper.style.display = "flex";
        gpuWakeBtn.style.display = "none";
        gpuSleepBtn.style.display = "none";
        
        enableChatUI(false, "Despertando GPU... Por favor, espera a que el modelo se active.");
        
        // Iniciar barra de progreso simulada si no está corriendo
        startProgressSimulation();
    } else {
        // "sleep" u otros
        gpuStatusBadge.textContent = "Reposo";
        gpuProgressWrapper.style.display = "none";
        gpuWakeBtn.style.display = "inline-block";
        gpuSleepBtn.style.display = "none";
        
        if (gpuProgressInterval) {
            clearInterval(gpuProgressInterval);
            gpuProgressInterval = null;
        }
        
        enableChatUI(false, "La GPU de Tenzor Nova está apagada. Haz clic en 'Activar' para despertarla.");
    }
}

function enableChatUI(enabled, disabledPlaceholder = "") {
    chatInput.disabled = !enabled;
    attachBtn.disabled = !enabled;
    
    if (enabled) {
        chatInput.placeholder = "Pregúntale a Tenzor sobre código o infraestructura...";
        updateSendButtonState();
    } else {
        chatInput.placeholder = disabledPlaceholder;
        sendBtn.disabled = true;
    }
}

function startProgressSimulation() {
    if (gpuProgressInterval) return;
    
    // Si ya hay un progreso previo, lo mantenemos, sino empezamos en 0
    if (gpuProgressValue <= 0 || gpuProgressValue >= 95) {
        gpuProgressValue = 0;
    }
    
    gpuProgressBarFill.style.width = gpuProgressValue + "%";
    gpuProgressText.textContent = `Activando... ${gpuProgressValue}%`;
    
    // Incrementar progreso simulando 3 minutos (180 segundos)
    // 95% / 180s = ~0.5% cada segundo
    gpuProgressInterval = setInterval(() => {
        if (gpuProgressValue < 95) {
            gpuProgressValue += 1;
            gpuProgressBarFill.style.width = gpuProgressValue + "%";
            gpuProgressText.textContent = `Levantando GPU... ${gpuProgressValue}%`;
        }
    }, 2000);
}

async function wakeGPU() {
    const apiKey = state.userApiKey;
    if (!apiKey) {
        alert("Por favor, introduce tu API Key en Ajustes primero.");
        return;
    }

    updateGPUStatus("waking");
    gpuProgressValue = 0;
    startProgressSimulation();

    try {
        const response = await fetch("/v1/model/wake", {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${apiKey}`
            }
        });
        if (response.ok) {
            // Comenzar polling de estado rápido mientras despierta
            startGPUPolling();
        } else {
            const errData = await response.json().catch(() => ({}));
            alert("Error al encender la GPU: " + (errData.detail || response.statusText));
            updateGPUStatus("sleep");
        }
    } catch (e) {
        alert("Error de red al intentar despertar la GPU.");
        updateGPUStatus("sleep");
    }
}

async function sleepGPU() {
    const apiKey = state.userApiKey;
    if (!apiKey) return;

    if (!confirm("¿Seguro que quieres apagar la GPU de Tenzor Nova inmediatamente? Esto interrumpirá las conversaciones activas.")) {
        return;
    }

    try {
        const response = await fetch("/v1/model/sleep", {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${apiKey}`
            }
        });
        if (response.ok) {
            updateGPUStatus("sleep");
        } else {
            const errData = await response.json().catch(() => ({}));
            alert("Error al apagar la GPU: " + (errData.detail || response.statusText));
        }
    } catch (e) {
        alert("Error de red al intentar apagar la GPU.");
    }
}

function startGPUPolling() {
    stopGPUPolling();
    // Consultar estado inmediatamente
    checkGPUStatus();
    // Consultar cada 15 segundos
    gpuPollingInterval = setInterval(checkGPUStatus, 15000);
}

function stopGPUPolling() {
    if (gpuPollingInterval) {
        clearInterval(gpuPollingInterval);
        gpuPollingInterval = null;
    }
}

