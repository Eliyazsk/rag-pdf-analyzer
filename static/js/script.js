document.addEventListener("DOMContentLoaded", () => {
    // Left panel elements
    const dropArea = document.getElementById("dropArea");
    const fileInput = document.getElementById("fileInput");
    const sourcesList = document.getElementById("sourcesList");
    const briefingBtn = document.getElementById("briefingBtn");
    const statusIndicator = document.getElementById("statusIndicator");
    const statusText = document.getElementById("statusText");
    const apiKeyInput = document.getElementById("apiKey");
    
    // Right panel elements
    const tabLinks = document.querySelectorAll(".tab-link");
    const tabContents = document.querySelectorAll(".tab-content");
    const chatForm = document.getElementById("chatForm");
    const userInput = document.getElementById("userInput");
    const messagesContainer = document.getElementById("messagesContainer");
    const sendBtn = document.getElementById("sendBtn");
    const guideContainer = document.getElementById("guideContainer");

    // Modal elements
    const summaryModal = document.getElementById("summaryModal");
    const closeModal = document.getElementById("closeModal");
    const modalTitle = document.getElementById("modalTitle");
    const modalBody = document.getElementById("modalBody");

    // Global client state
    let sources = []; // Array of { name: string, active: boolean, size: string }

    function setStatus(state, message) {
        statusIndicator.className = `status-indicator ${state}`;
        statusText.textContent = message;
    }

    // Tab Switching
    tabLinks.forEach(link => {
        link.addEventListener("click", () => {
            tabLinks.forEach(l => l.classList.remove("active"));
            tabContents.forEach(c => c.classList.remove("active"));
            
            link.classList.add("active");
            const tabId = link.getAttribute("data-tab");
            document.getElementById(`${tabId}Tab`).classList.add("active");
        });
    });

    // Suggested prompts buttons click logic
    const suggestionChips = document.querySelectorAll(".suggestion-chip-btn");
    suggestionChips.forEach(chip => {
        chip.addEventListener("click", () => {
            const query = chip.getAttribute("data-query");
            userInput.value = query;
            // Submit the form
            chatForm.requestSubmit();
        });
    });

    // Ingestion Handlers
    dropArea.addEventListener("click", () => fileInput.click());

    dropArea.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropArea.classList.add("dragover");
    });

    ["dragleave", "drop"].forEach(eventName => {
        dropArea.addEventListener(eventName, () => dropArea.classList.remove("dragover"));
    });

    dropArea.addEventListener("drop", (e) => {
        e.preventDefault();
        uploadFiles(e.dataTransfer.files);
    });

    fileInput.addEventListener("change", (e) => {
        uploadFiles(e.target.files);
    });

    // Upload files to server
    async function uploadFiles(files) {
        const pdfFiles = Array.from(files).filter(f => f.type === "application/pdf");
        if (pdfFiles.length === 0) {
            alert("Please select PDF documents to upload.");
            return;
        }

        setStatus("processing", "Processing PDF sources...");
        const formData = new FormData();
        pdfFiles.forEach(file => formData.append("files", file));
        
        const keyOverride = apiKeyInput.value.trim();
        if (keyOverride) {
            formData.append("api_key", keyOverride);
        }

        try {
            const response = await fetch("/upload", {
                method: "POST",
                body: formData
            });
            const data = await response.json();

            if (response.ok) {
                setStatus("ready", "Sources loaded!");
                // Add uploaded files to our sources state
                pdfFiles.forEach(file => {
                    const exists = sources.some(s => s.name === file.name);
                    if (!exists) {
                        sources.push({
                            name: file.name,
                            active: true,
                            size: formatBytes(file.size)
                        });
                    }
                });
                renderSources();
                addMessage("assistant", `Successfully imported ${pdfFiles.length} new source(s)! They are now active in the left panel.`);
            } else {
                setStatus("error", "Processing failed");
                alert(`Error: ${data.error}`);
            }
        } catch (error) {
            console.error(error);
            setStatus("error", "Network error");
            alert("Network error: Could not upload documents.");
        }
    }

    // Render left panel sources list
    function renderSources() {
        // Update stats badge in UI
        const activeCount = sources.filter(s => s.active).length;
        const countBadge = document.getElementById("sourcesCount");
        if (countBadge) {
            countBadge.textContent = `${activeCount} Active`;
        }

        if (sources.length === 0) {
            sourcesList.innerHTML = `<div class="empty-sources-state">No sources added yet. Upload PDFs above!</div>`;
            return;
        }

        sourcesList.innerHTML = "";
        sources.forEach(source => {
            const card = document.createElement("div");
            card.className = `source-card ${source.active ? '' : 'inactive'}`;
            card.innerHTML = `
                <input type="checkbox" class="source-card-checkbox" ${source.active ? 'checked' : ''} data-name="${source.name}">
                <div class="source-card-details">
                    <div class="source-card-name" title="${source.name}">${source.name}</div>
                    <div class="source-card-meta">${source.size}</div>
                </div>
                <div class="source-card-actions">
                    <button class="action-icon-btn summary-btn" data-name="${source.name}" title="View Summary">👁️</button>
                    <button class="action-icon-btn delete-btn" data-name="${source.name}" title="Remove Source">🗑️</button>
                </div>
            `;
            sourcesList.appendChild(card);
        });

        // Checkbox events
        document.querySelectorAll(".source-card-checkbox").forEach(box => {
            box.addEventListener("change", () => {
                const name = box.getAttribute("data-name");
                const source = sources.find(s => s.name === name);
                if (source) {
                    source.active = box.checked;
                    renderSources();
                }
            });
        });

        // Summary Modal Trigger
        document.querySelectorAll(".summary-btn").forEach(btn => {
            btn.addEventListener("click", () => {
                const name = btn.getAttribute("data-name");
                showSummary(name);
            });
        });

        // Delete Trigger
        document.querySelectorAll(".delete-btn").forEach(btn => {
            btn.addEventListener("click", () => {
                const name = btn.getAttribute("data-name");
                deleteSource(name);
            });
        });
    }

    // Delete source
    async function deleteSource(name) {
        if (!confirm(`Are you sure you want to remove source "${name}"?`)) return;
        
        setStatus("processing", "Removing source...");
        try {
            const keyOverride = apiKeyInput.value.trim();
            const response = await fetch("/delete_source", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ filename: name, api_key: keyOverride })
            });

            if (response.ok) {
                sources = sources.filter(s => s.name !== name);
                renderSources();
                setStatus("ready", "Source removed");
                addMessage("assistant", `Removed source document "${name}" from your workspace.`);
            } else {
                const data = await response.json();
                setStatus("error", "Remove failed");
                alert(`Error: ${data.error}`);
            }
        } catch (error) {
            console.error(error);
            setStatus("error", "Network error");
            alert("Network error: Could not contact server to delete file.");
        }
    }

    // Display summary modal
    async function showSummary(name) {
        modalTitle.textContent = `Summary: ${name}`;
        modalBody.innerHTML = `<div class="typing-indicator"><span></span><span></span><span></span></div>`;
        summaryModal.style.display = "block";

        const keyOverride = apiKeyInput.value.trim();
        try {
            const response = await fetch("/summary", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ filename: name, api_key: keyOverride })
            });
            const data = await response.json();

            if (response.ok) {
                modalBody.innerHTML = parseMarkdown(data.summary);
            } else {
                modalBody.innerHTML = `<p class="error">❌ Error: ${data.error}</p>`;
            }
        } catch (e) {
            modalBody.innerHTML = `<p class="error">❌ Network error occurred while generating summary.</p>`;
        }
    }

    // Modal Close
    closeModal.onclick = () => summaryModal.style.display = "none";
    window.onclick = (e) => {
        if (e.target === summaryModal) summaryModal.style.display = "none";
    }

    // Generate Notebook Study Guide
    briefingBtn.addEventListener("click", async () => {
        const activeFiles = sources.filter(s => s.active).map(s => s.name);
        if (activeFiles.length === 0) {
            alert("Please select at least one active source checkbox first.");
            return;
        }

        // Switch Tab
        document.querySelector("[data-tab='guide']").click();
        
        guideContainer.innerHTML = `
            <div class="empty-guide-state">
                <div class="typing-indicator" style="justify-content: center; margin-bottom: 12px;">
                    <span></span><span></span><span></span>
                </div>
                <h3>Generating Notebook Study Guide...</h3>
                <p>Synthesizing all active sources into a structured brief. This may take up to 20 seconds.</p>
            </div>
        `;

        const keyOverride = apiKeyInput.value.trim();
        try {
            const response = await fetch("/briefing", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ active_sources: activeFiles, api_key: keyOverride })
            });
            const data = await response.json();

            if (response.ok) {
                guideContainer.innerHTML = `<div class="markdown-body">${parseMarkdown(data.briefing)}</div>`;
            } else {
                guideContainer.innerHTML = `
                    <div class="empty-guide-state">
                        <h3 style="color:#ff4757">Generation Failed</h3>
                        <p>${data.error}</p>
                    </div>
                `;
            }
        } catch (error) {
            guideContainer.innerHTML = `
                <div class="empty-guide-state">
                    <h3 style="color:#ff4757">Network Error</h3>
                    <p>Could not connect to the server to generate briefing guide.</p>
                </div>
            `;
        }
    });

    // Chat Submission
    chatForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const question = userInput.value.trim();
        if (!question) return;

        addMessage("user", question);
        userInput.value = "";

        const activeFiles = sources.filter(s => s.active).map(s => s.name);
        const typingId = showTypingIndicator();
        sendBtn.disabled = true;

        const payload = {
            question: question,
            active_sources: activeFiles
        };

        const keyOverride = apiKeyInput.value.trim();
        if (keyOverride) {
            payload.api_key = keyOverride;
        }

        try {
            const response = await fetch("/ask", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const data = await response.json();

            removeTypingIndicator(typingId);

            if (response.ok) {
                addMessage("assistant", data.answer, data.citations);
            } else {
                addMessage("assistant", `❌ Error: ${data.error}`);
            }
        } catch (error) {
            removeTypingIndicator(typingId);
            addMessage("assistant", "❌ Network error: Could not contact search server.");
        } finally {
            sendBtn.disabled = false;
            userInput.focus();
        }
    });

    // UI rendering helpers
    function addMessage(sender, text, citations = null) {
        const msg = document.createElement("div");
        msg.className = `message ${sender}`;
        
        let citationsHTML = "";
        if (citations && citations.length > 0) {
            citationsHTML = `<div class="citations-container">`;
            citations.forEach(cit => {
                citationsHTML += `<span class="citation-chip" title="Click to view details" data-source="${cit.source}" data-page="${cit.page}">📄 ${cit.source} (p. ${cit.page})</span>`;
            });
            citationsHTML += `</div>`;
        }

        msg.innerHTML = `
            <div class="message-avatar">${sender === 'user' ? '👤' : '🤖'}</div>
            <div class="message-wrapper">
                <div class="message-content">${escapeHTML(text).replace(/\n/g, '<br>')}</div>
                ${citationsHTML}
            </div>
        `;
        messagesContainer.appendChild(msg);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;

        // Chip click events
        msg.querySelectorAll(".citation-chip").forEach(chip => {
            chip.addEventListener("click", () => {
                const source = chip.getAttribute("data-source");
                const page = chip.getAttribute("data-page");
                alert(`Citation details:\nSource file: ${source}\nPage number: ${page}`);
            });
        });
    }

    function showTypingIndicator() {
        const id = "typing-" + Date.now();
        const indicator = document.createElement("div");
        indicator.className = "message assistant";
        indicator.id = id;
        indicator.innerHTML = `
            <div class="message-avatar">🤖</div>
            <div class="message-content">
                <div class="typing-indicator">
                    <span></span>
                    <span></span>
                    <span></span>
                </div>
            </div>
        `;
        messagesContainer.appendChild(indicator);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
        return id;
    }

    function removeTypingIndicator(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }

    function formatBytes(bytes, decimals = 1) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }

    function escapeHTML(str) {
        return str
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // Markdown simple parser logic
    function parseMarkdown(text) {
        if (!text) return "";
        let html = text;
        // Escapes HTML tags
        html = escapeHTML(html);
        
        // Headers
        html = html.replace(/^### (.*$)/gim, '<h3>$1</h3>');
        html = html.replace(/^## (.*$)/gim, '<h2>$1</h2>');
        html = html.replace(/^# (.*$)/gim, '<h1>$1</h1>');
        
        // Bold
        html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        
        // Lists
        html = html.replace(/^\* (.*$)/gim, '<li>$1</li>');
        html = html.replace(/^- (.*$)/gim, '<li>$1</li>');
        html = html.replace(/(<li>.*<\/li>)/gim, '<ul>$1</ul>');
        html = html.replace(/<\/ul>\s*<ul>/g, ''); // Merges consecutive list elements
        
        // Split paragraphs
        html = html.split('\n\n').map(p => {
            if (!p.trim()) return "";
            if (!p.trim().startsWith('<h') && !p.trim().startsWith('<ul') && !p.trim().startsWith('<li')) {
                return `<p>${p.replace(/\n/g, '<br>')}</p>`;
            }
            return p;
        }).join('\n');
        
        return html;
    }
});
