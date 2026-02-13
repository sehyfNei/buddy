// ── PDF.js Setup ────────────────────────────────────────────────────────────

const pdfjsLib = await import("https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.min.mjs");
pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.worker.min.mjs";

// ── DOM Elements ────────────────────────────────────────────────────────────

const fileInput = document.getElementById("file-input");
const filenameEl = document.getElementById("filename");
const canvas = document.getElementById("pdf-canvas");
const emptyState = document.getElementById("empty-state");
const prevBtn = document.getElementById("prev-btn");
const nextBtn = document.getElementById("next-btn");
const pageInfo = document.getElementById("page-info");
const chatInput = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");
const messagesEl = document.getElementById("buddy-messages");
const stateEl = document.getElementById("buddy-state");
const healthDot = document.getElementById("health-dot");

const ctx = canvas.getContext("2d");

// ── State ───────────────────────────────────────────────────────────────────

let pdfDoc = null;
let currentPage = 1;
let totalPages = 0;
let sessionId = null;
let rendering = false;
let lastScrollY = 0;
let scrollBackCount = 0;
let signalInterval = null;
let stateInterval = null;

// ── PDF Upload ──────────────────────────────────────────────────────────────

fileInput.addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    // Upload to backend for text extraction
    const formData = new FormData();
    formData.append("file", file);

    try {
        const resp = await fetch("/api/upload", { method: "POST", body: formData });
        if (!resp.ok) {
            const err = await resp.json();
            addMessage("system", `Error: ${err.detail || "Upload failed"}`);
            return;
        }
        const data = await resp.json();
        sessionId = data.session_id;
        totalPages = data.total_pages;
        filenameEl.textContent = data.filename;

        // Load PDF in viewer
        const arrayBuf = await file.arrayBuffer();
        pdfDoc = await pdfjsLib.getDocument({ data: arrayBuf }).promise;

        currentPage = 1;
        renderPage(currentPage);
        updateNavigation();
        enableChat();
        startSignalCapture();
        startStatePolling();

        addMessage("system", `Loaded "${data.filename}" (${totalPages} pages). I'm here if you need help!`);
    } catch (err) {
        addMessage("system", `Upload error: ${err.message}`);
    }
});

// ── PDF Rendering ───────────────────────────────────────────────────────────

async function renderPage(pageNum) {
    if (!pdfDoc || rendering) return;
    rendering = true;

    const page = await pdfDoc.getPage(pageNum);
    const scale = Math.min(
        (document.getElementById("pdf-panel").clientWidth - 40) / page.getViewport({ scale: 1 }).width,
        2.0
    );
    const viewport = page.getViewport({ scale });

    canvas.width = viewport.width;
    canvas.height = viewport.height;
    canvas.style.display = "block";
    emptyState.style.display = "none";

    await page.render({ canvasContext: ctx, viewport }).promise;
    rendering = false;

    // Signal page view to backend
    sendSignal("page_view", pageNum);
}

function updateNavigation() {
    pageInfo.textContent = `Page ${currentPage} of ${totalPages}`;
    prevBtn.disabled = currentPage <= 1;
    nextBtn.disabled = currentPage >= totalPages;
}

prevBtn.addEventListener("click", () => {
    if (currentPage > 1) {
        currentPage--;
        renderPage(currentPage);
        updateNavigation();
    }
});

nextBtn.addEventListener("click", () => {
    if (currentPage < totalPages) {
        // Detect page skipping (jumping ahead multiple pages)
        const jump = 1; // single-page nav is normal
        currentPage++;
        renderPage(currentPage);
        updateNavigation();
    }
});

// ── Keyboard Navigation ────────────────────────────────────────────────────

document.addEventListener("keydown", (e) => {
    if (e.target === chatInput) return; // don't capture when typing

    if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
        prevBtn.click();
    } else if (e.key === "ArrowRight" || e.key === "ArrowDown") {
        nextBtn.click();
    }
});

// ── Signal Capture ──────────────────────────────────────────────────────────

function sendSignal(eventType, page = currentPage, data = {}) {
    fetch("/api/signal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event_type: eventType, page, data }),
    }).catch(() => {}); // fire-and-forget
}

function startSignalCapture() {
    // Track scroll direction in PDF panel for re-reading detection
    const pdfPanel = document.getElementById("pdf-panel");
    pdfPanel.addEventListener("scroll", () => {
        const scrollY = pdfPanel.scrollTop;
        if (scrollY < lastScrollY - 50) {
            scrollBackCount++;
            sendSignal("scroll_back", currentPage);
        }
        lastScrollY = scrollY;
    });

    // Track text selection
    document.addEventListener("selectionchange", () => {
        const sel = window.getSelection();
        if (sel && sel.toString().trim().length > 0) {
            sendSignal("selection", currentPage, { text: sel.toString().substring(0, 200) });
        }
    });
}

// ── State Polling ───────────────────────────────────────────────────────────

function startStatePolling() {
    if (stateInterval) clearInterval(stateInterval);

    stateInterval = setInterval(async () => {
        try {
            const resp = await fetch("/api/state");
            if (!resp.ok) return;
            const data = await resp.json();

            // Update state badge
            stateEl.textContent = data.state;
            stateEl.className = "state-badge " + data.state;

            // Show intervention message if Buddy has something to say
            if (data.should_intervene && data.message) {
                addMessage("intervention", data.message);
            }
        } catch {}
    }, 5000); // poll every 5 seconds
}

// ── Chat ────────────────────────────────────────────────────────────────────

function enableChat() {
    chatInput.disabled = false;
    sendBtn.disabled = false;
}

async function sendChat() {
    const message = chatInput.value.trim();
    if (!message) return;

    addMessage("user", message);
    chatInput.value = "";
    sendBtn.disabled = true;

    try {
        const resp = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message, page: currentPage }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            addMessage("system", `Error: ${err.detail || "Chat failed"}`);
        } else {
            const data = await resp.json();
            addMessage("buddy", data.reply);
        }
    } catch (err) {
        addMessage("system", `Connection error: ${err.message}`);
    }

    sendBtn.disabled = false;
}

sendBtn.addEventListener("click", sendChat);
chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendChat();
    }
});

// ── Message Display ─────────────────────────────────────────────────────────

function addMessage(type, text) {
    const div = document.createElement("div");
    div.className = `buddy-message ${type}`;
    div.textContent = text;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ── Health Check ────────────────────────────────────────────────────────────

async function checkHealth() {
    try {
        const resp = await fetch("/api/health");
        if (resp.ok) {
            const data = await resp.json();
            healthDot.className = "health-dot " + (data.llm_connected ? "online" : "offline");
            healthDot.title = data.llm_connected ? "LLM connected" : "LLM disconnected";
        }
    } catch {
        healthDot.className = "health-dot offline";
        healthDot.title = "Server unreachable";
    }
}

// Check health on load and every 30s
checkHealth();
setInterval(checkHealth, 30000);
