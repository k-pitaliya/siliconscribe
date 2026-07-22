document.addEventListener('DOMContentLoaded', () => {

    // Slider value update
    const slider = document.querySelector('.slider');
    const sliderVal = document.querySelector('.slider-val');
    
    slider.addEventListener('input', (e) => {
        sliderVal.textContent = `${e.target.value} MHz`;
    });

    // Tab Logic
    const setupTabs = (tabSelector, contentNodes) => {
        const tabs = document.querySelectorAll(tabSelector);
        
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                // Remove active from all siblings
                tabs.forEach(t => t.classList.remove('active'));
                // Add to clicked
                tab.classList.add('active');
                
                // Show content (mock logic, normally we'd switch displays)
                // For demonstration, we could add logic to hide/show specific divs
            });
        });
    };

    setupTabs('.editor-tabs .tab');
    setupTabs('.results-tabs .tab');

    const rtlEditorTab = document.querySelector('.editor-tabs .tab[data-target="rtl-editor"]');
    const tbEditorTab = document.querySelector('.editor-tabs .tab[data-target="tb-editor"]');
    const codeContent = document.querySelector('.code-container pre code');

    rtlEditorTab.addEventListener('click', () => {
        codeContent.innerHTML = `<span class="keyword">module</span> alu_4bit #(
    <span class="keyword">parameter</span> WIDTH = 4
)(
    <span class="keyword">input</span>  [WIDTH-1:0] a,
    <span class="keyword">input</span>  [WIDTH-1:0] b,
    <span class="keyword">input</span>  [2:0]       opcode,
    <span class="keyword">output</span> <span class="keyword">reg</span> [WIDTH-1:0] result,
    <span class="keyword">output</span> <span class="keyword">reg</span>         overflow
);
    
    <span class="keyword">always_comb</span> <span class="keyword">begin</span>
        <span class="comment">// Wait for AI generation</span>
    <span class="keyword">end</span>
<span class="keyword">endmodule</span>`;
    });

    tbEditorTab.addEventListener('click', () => {
        codeContent.innerHTML = `<span class="keyword">module</span> tb_alu_4bit;
    <span class="keyword">reg</span> [3:0] a, b;
    <span class="keyword">reg</span> [2:0] opcode;
    <span class="keyword">wire</span> [3:0] result;
    <span class="keyword">wire</span> overflow;

    alu_4bit #(4) dut (.*);

    <span class="keyword">initial</span> <span class="keyword">begin</span>
        <span class="comment">// Wait for AI generation</span>
    <span class="keyword">end</span>
<span class="keyword">endmodule</span>`;
    });

    // Chat Logic
    const chatInput = document.querySelector('.chat-input-area input');
    const sendBtn = document.querySelector('.chat-input-area .icon-btn');
    const messagesContainer = document.querySelector('.chat-messages');

    const addMessage = (text, isAi = false) => {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${isAi ? 'ai-msg' : 'user-msg'}`;
        
        msgDiv.innerHTML = `
            ${isAi ? `<div class="msg-avatar"><i class="fa-solid fa-robot"></i></div>` : `<div class="msg-avatar" style="background: rgba(16, 185, 129, 0.2); color: #10B981;"><i class="fa-solid fa-user"></i></div>`}
            <div class="msg-bubble" style="${!isAi ? 'background: rgba(99, 102, 241, 0.2);' : ''}">
                <p>${text}</p>
            </div>
        `;
        
        messagesContainer.appendChild(msgDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    };

    const handleSend = () => {
        const text = chatInput.value.trim();
        if(!text) return;
        
        addMessage(text, false);
        chatInput.value = '';

        // Mock AI response
        setTimeout(() => {
            addMessage("I'm analyzing your request. I will generate the required modules shortly.", true);
        }, 1000);
    };

    sendBtn.addEventListener('click', handleSend);
    chatInput.addEventListener('keypress', (e) => {
        if(e.key === 'Enter') handleSend();
    });

    // Generate Button Logic
    const genBtn = document.getElementById('generate-btn');
    const promptInput = document.getElementById('prompt-input');

    genBtn.addEventListener('click', () => {
        const promptText = promptInput.value.trim();
        if(!promptText) {
            promptInput.style.borderColor = '#EF4444';
            setTimeout(() => promptInput.style.borderColor = 'var(--border-glass)', 1000);
            return;
        }

        const ogText = genBtn.innerHTML;
        genBtn.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> <span>Generating...</span>`;
        genBtn.style.opacity = '0.7';
        
        addMessage(`Requesting generation for: "${promptText.substring(0, 50)}..."`, false);

        setTimeout(() => {
            genBtn.innerHTML = ogText;
            genBtn.style.opacity = '1';
            
            addMessage("Generation complete. I've created the RTL and a basic SystemVerilog Testbench. Simulating...", true);
            
            // Populate code
            rtlEditorTab.click();
            codeContent.innerHTML = codeContent.innerHTML.replace('<span class="comment">// Wait for AI generation</span>', `<span class="keyword">case</span>(opcode)
            3'b000: {overflow, result} = a + b;
            3'b001: {overflow, result} = a - b;
            3'b010: result = a & b;
            3'b011: result = a | b;
            3'b100: result = a ^ b;
            <span class="keyword">default</span>: result = '0;
        <span class="keyword">endcase</span>`);

            setTimeout(() => {
                addMessage("Simulation finished. 98/100 tests passed. There's a subtle failure in the subtraction overflow logic. Check the schematic and waveform.", true);
            }, 2000);

        }, 2500);
    });
});
