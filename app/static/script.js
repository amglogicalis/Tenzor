// ⚙️ Configuración del estado global
let state = {
    chats: [],                 // Array de chats: { id, title, messages: [{ role, content }] }
    activeChatId: null,        // ID del chat seleccionado
    defaultApiKey: "",         // Clave por defecto entregada por el servidor
    userApiKey: "",            // Clave del cliente configurada en Ajustes (localStorage)
    chatIdBeingRenamed: null   // ID del chat que se está renombrando actualmente
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

// Selector Ajustes Modal
const settingsBtn = document.getElementById("settings-btn");
const settingsModal = document.getElementById("settings-modal");
const closeSettingsModalBtn = document.getElementById("close-settings-modal-btn");
const cancelSettingsBtn = document.getElementById("cancel-settings-btn");
const saveSettingsBtn = document.getElementById("save-settings-btn");
const settingsApiKeyInput = document.getElementById("settings-api-key");

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

    // 2. Obtener clave por defecto del servidor
    await fetchDefaultConfig();

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
});

// 🌐 Peticiones API a Tenzor Backend
async function fetchDefaultConfig() {
    try {
        const response = await fetch("/v1/config");
        if (response.ok) {
            const data = await response.json();
            state.defaultApiKey = data.default_api_key || "";
            console.log("Configuración por defecto del servidor cargada.");
        }
    } catch (e) {
        console.error("Error obteniendo clave por defecto del servidor:", e);
    }
}

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
        sendBtn.disabled = chatInput.value.trim() === "";
    });

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
        settingsModal.classList.add("open");
    });
    
    const closeSettings = () => settingsModal.classList.remove("open");
    closeSettingsModalBtn.addEventListener("click", closeSettings);
    cancelSettingsBtn.addEventListener("click", closeSettings);

    saveSettingsBtn.addEventListener("click", () => {
        state.userApiKey = settingsApiKeyInput.value.trim();
        localStorage.setItem("tenzor_user_api_key", state.userApiKey);
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
            appendMessageMarkup(msg.role, msg.content);
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
async function sendMessage() {
    const text = chatInput.value.trim();
    if (!text) return;

    // Si no hay un chat activo, crearlo
    if (!state.activeChatId) {
        createNewChat();
    }

    const activeChat = state.chats.find(c => c.id === state.activeChatId);
    if (!activeChat) return;

    // Limpiar input
    chatInput.value = "";
    chatInput.style.height = "auto";
    sendBtn.disabled = true;

    // Ocultar pantalla de bienvenida
    welcomeScreen.style.display = "none";

    // 1. Agregar y mostrar mensaje del usuario
    const userMessage = { role: "user", content: text };
    activeChat.messages.push(userMessage);
    appendMessageMarkup("user", text);
    scrollToBottom();

    // 2. Si el título del chat es el genérico inicial, renombrarlo automáticamente con las primeras palabras
    if (activeChat.title.startsWith("Nuevo Chat ")) {
        activeChat.title = text.length > 25 ? text.substring(0, 22) + "..." : text;
        renderChatList();
    }

    // Guardar estado local
    saveChatsToStorage();

    // 3. Crear contenedor y animación de carga para la respuesta del asistente
    const typingIndicator = appendTypingIndicator();
    scrollToBottom();

    // 4. Obtener clave de autorización a enviar
    const apiKeyToSend = state.userApiKey || state.defaultApiKey;
    if (!apiKeyToSend) {
        removeTypingIndicator(typingIndicator);
        appendMessageMarkup("assistant", "⚠️ Error: No has configurado tu API Key de Tenzor y tampoco hay una por defecto en el servidor. Configúrala en Ajustes.");
        scrollToBottom();
        return;
    }

    // 5. Enviar petición HTTP al Backend
    try {
        const response = await fetch("/v1/chat/completions", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${apiKeyToSend}`
            },
            body: JSON.stringify({
                model: "tenzor-dev",
                messages: activeChat.messages,
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
function appendMessageMarkup(role, content) {
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

    // Si es asistente, procesar Markdown; si es usuario, texto plano seguro
    if (role === "assistant") {
        body.innerHTML = marked.parse(content);
        // Formatear código e inyectar botones de copiar
        formatAndAddCopyButtons(body);
    } else {
        const p = document.createElement("p");
        p.textContent = content;
        body.appendChild(p);
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
