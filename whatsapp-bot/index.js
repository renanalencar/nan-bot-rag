const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const axios = require('axios');
const fs = require('fs');
const path = require('path');
const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8000/api/chat';

// Map para armazenar os chats pausados e seus respectivos timeouts
const pausedChats = new Map();

const puppeteerOptions = {
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
    executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || '/usr/bin/chromium'
};

// Cleanup Chromium lock files before starting to prevent "profile in use" error
const authDir = path.join(__dirname, '.wwebjs_auth');

const cleanLockFiles = (dir) => {
    if (!fs.existsSync(dir)) return;
    const items = fs.readdirSync(dir);
    for (const item of items) {
        const fullPath = path.join(dir, item);
        try {
            if (fs.lstatSync(fullPath).isDirectory()) {
                cleanLockFiles(fullPath);
            } else if (item.startsWith('Singleton')) {
                try {
                    fs.unlinkSync(fullPath);
                    console.log(`[INIT] Removed stale lock file: ${fullPath}`);
                } catch (e) {
                    console.error(`[INIT] Failed to remove lock file ${fullPath}:`, e.message);
                }
            }
        } catch (err) {
            // Ignorar erros caso o arquivo tenha sido removido após o readdirSync ou seja um symlink quebrado
        }
    }
};

cleanLockFiles(authDir);

// Configure the client with LocalAuth to save session state so you don't have to scan QR every time
const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: puppeteerOptions
});

// Generate and display the QR code
client.on('qr', (qr) => {
    console.log('\n\nSCAN THE QR CODE BELOW WITH WHATSAPP:');
    qrcode.generate(qr, { small: true });
});

// Client is ready
client.on('ready', () => {
    console.log('\nClient is ready! Listening for messages (including in groups)...');
});

// Listen for incoming messages
client.on('message_create', async (message) => {
    // Comando para reativar o bot no chat
    if (message.body.trim() === '!nan') {
        const targetChat = message.fromMe ? message.to : message.from;
        if (pausedChats.has(targetChat)) {
            clearTimeout(pausedChats.get(targetChat)); // Cancela o timer
            pausedChats.delete(targetChat);
            await client.sendMessage(targetChat, "🤖 NaN reativado! O atendimento automático voltou.");
            console.log(`\n[HANDOFF] Bot reativado manualmente para o chat: ${targetChat}`);
        }
        return;
    }

    // Ignore as nossas próprias mensagens
    if (message.fromMe) return;

    // Ignore status updates
    if (message.from === 'status@broadcast') return;

    // Tratamento de download de arquivos
    if (message.hasMedia) {
        try {
            const media = await message.downloadMedia();
            if (media) {
                // Lista de mimetypes permitidos (PDF, Word, Excel, Markdown, Txt)
                const acceptedMimeTypes = [
                    'application/pdf', 
                    'application/msword', 
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document', // docx
                    'application/vnd.ms-excel',
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', // xlsx
                    'text/markdown',
                    'text/plain'
                ];
                
                if (acceptedMimeTypes.includes(media.mimetype)) {
                    console.log(`\n[DOWNLOAD] Documento recebido: ${media.filename || 'sem_nome'}`);
                    
                    // A pasta docs/ fica na raiz do projeto
                    const docsDir = path.join(__dirname, '..', 'docs');
                    if (!fs.existsSync(docsDir)){
                        fs.mkdirSync(docsDir, { recursive: true });
                    }
                    
                    // Tratamento de extensão genérica caso venha sem nome
                    const fallbackExt = media.mimetype === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' ? 'docx' : 
                                       (media.mimetype === 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' ? 'xlsx' : 
                                        media.mimetype.split('/')[1]);
                    
                    const filename = media.filename || `documento_${Date.now()}.${fallbackExt}`;
                    const filepath = path.join(docsDir, filename);
                    
                    fs.writeFileSync(filepath, Buffer.from(media.data, 'base64'));
                    console.log(`[DOWNLOAD] Arquivo salvo em: ${filepath}`);
                    
                    await client.sendMessage(message.from, `📄 Recebi seu arquivo *${filename}* e o salvei no diretório com sucesso.`);
                    
                    // Se a mensagem enviada for SÓ o arquivo (sem nenhum texto), não processa o RAG
                    if (!message.body) return;
                }
            }
        } catch (downloadErr) {
            console.error('[DOWNLOAD] Falha ao baixar mídia:', downloadErr);
        }
    }

    // Check if it has a body text
    if (!message.body) return;

    // Se este chat estiver pausado, ignoramos a mensagem
    if (pausedChats.has(message.from)) return;

    console.log(`\nReceived message from ${message.from}: ${message.body}`);

    try {
        // WhatsApp Web atualizou recentemente e quebrou a função message.getChat() na biblioteca (erro "r").
        // Felizmente, não precisamos dela! Podemos descobrir se é grupo apenas olhando o final do ID.
        const isGroup = message.from.includes('@g.us');

        // Prepare the payload for our Python RAG backend
        const payload = {
            message: message.body,
            sender_id: message.from,
            is_group: isGroup
        };

        // Call the FastAPI Python endpoint
        console.log('\nPayload montado:', payload);
        console.log(`Processing via Python RAG Pipeline at ${backendUrl} ...`);
        const response = await axios.post(backendUrl, payload);

        if (response.data && response.data.reply) {
            // Reply back to the same chat (group or private)
            await client.sendMessage(message.from, response.data.reply);
            console.log('Replied successfully.');
        } else if (response.data && response.data.handoff) {
            // Se já existir um timeout, cancela para recomeçar o contador
            if (pausedChats.has(message.from)) {
                clearTimeout(pausedChats.get(message.from));
            }

            // Define um timeout (ex: 15 minutos) para reativar o bot automaticamente
            const timeoutId = setTimeout(async () => {
                if (pausedChats.has(message.from)) {
                    pausedChats.delete(message.from);
                    try {
                        await client.sendMessage(message.from, "🤖 NaN reativado automaticamente por tempo de inatividade.");
                    } catch (err) { }
                    console.log(`\n[HANDOFF] Timeout expirado. Bot reativado para: ${message.from}`);
                }
            }, 15 * 60 * 1000); // 15 minutos em milissegundos

            pausedChats.set(message.from, timeoutId);
            await client.sendMessage(message.from, "Não tenho essa informação no momento. Vou te transferir para Renan. Ele deve te responder em breve!\n_(Para voltar a falar comigo a qualquer momento, digite `!nan`)_");
            console.log(`\n[HANDOFF] Chat pausado para: ${message.from}`);
        }

    } catch (error) {
        console.error('\n=== ERROR DETAILS ===');
        console.error('Full Error:', error);
        if (error.response) {
            console.error('Response data:', error.response.data);
        }
        console.error('=====================\n');
    }
});

// Initialize the client
client.initialize();
