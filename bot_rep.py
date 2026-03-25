import os
import sys
import discord
from discord.ext import commands, tasks
import psycopg2
from dotenv import load_dotenv
import requests
import io
import asyncio
import re
import aiohttp
from bs4 import BeautifulSoup
from discord.ext import tasks
from deep_translator import GoogleTranslator
from datetime import datetime

# --- CONFIGURAÇÕES ---
def carregar_config():
    load_dotenv(override=True)
    if not os.getenv('DISCORD_TOKEN'):
        diretorio_script = os.path.dirname(os.path.abspath(__file__))
        caminho_env = os.path.join(diretorio_script, '.env')
        if os.path.exists(caminho_env):
            with open(caminho_env, "r", encoding="utf-8") as f:
                for linha in f:
                    if "=" in linha and not linha.startswith("#"):
                        k, v = linha.split("=", 1)
                        os.environ[k.strip()] = v.strip().replace('"', '').replace("'", "")

carregar_config()

TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID', 0))
ID_FORUM_TROCA = 1434310955004592360
ID_CANAL_STAFF = 1412423356946317350
ID_CANAL_RAID = 1412423357600632922
# IDs dos Canais que criam as salas (os gatilhos)
ID_HUB_DUO = 1486348560822960128  # Canal "➕ Criar DUO"
ID_HUB_TRIO = 1486348629550825653 # Canal "➕ Criar TRIO"
# IDs das Categorias onde as salas serão criadas
ID_CAT_DUO = 1486347910885937242   # Categoria para DUOS
ID_CAT_TRIO = 1486348090741883114  # Categoria para TRIOS

if not TOKEN:
    print("❌ ERRO: DISCORD_TOKEN não encontrado!")
    sys.exit(1)

# --- CONFIGURAÇÃO DO BOT ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True # <-- ESSA LINHA É OBRIGATÓRIA
bot = commands.Bot(command_prefix="/", intents=intents)

# IDs de Configuração
CANAL_NOTICIAS_ID = 1412423357541908524
CANAL_MIDIA_ID = 1412423357382529098
URL_BASE = "https://arcraiders.com"
URL_NEWS = "https://arcraiders.com/news"
ULTIMA_NOTICIA_URL = None

# --- TRADUTOR DE NOTÍCIAS DO SITE E EXTRATOR DE MÍDIAS OFICIAIS ---
@tasks.loop(minutes=15)
async def monitorar_noticias_pro():
    global ULTIMA_NOTICIA_URL
    
    print(f"--- [LOG {datetime.now().strftime('%H:%M:%S')}] Iniciando varredura no site oficial ---")
    
    timeout = aiohttp.ClientTimeout(total=40)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(URL_NEWS) as response:
                if response.status != 200:
                    print(f"⚠️ Erro ao acessar o site: Status {response.status}")
                    return
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Identifica links de notícias
                links_news = [a for a in soup.find_all('a', href=True) if '/news/' in a['href']]
                
                if not links_news:
                    print("🔍 Nenhuma notícia encontrada no feed principal.")
                    return
                
                url_relativa = links_news[0]['href']
                url_completa = f"{URL_BASE}{url_relativa}" if url_relativa.startswith('/') else url_relativa
                
                if url_completa == ULTIMA_NOTICIA_URL:
                    print("✅ Nenhuma novidade. O site continua com a mesma notícia no topo.")
                    return
                
                print(f"🆕 NOVA NOTÍCIA DETECTADA: {url_completa}")
                ULTIMA_NOTICIA_URL = url_completa

                # --- ENTRANDO NA NOTÍCIA ---
                async with session.get(url_completa) as resp_interna:
                    html_interno = await resp_interna.text()
                    soup_int = BeautifulSoup(html_interno, 'html.parser')
                    
                    titulo_tag = soup_int.find('h1') or soup_int.find('h2')
                    titulo_en = titulo_tag.text.strip() if titulo_tag else "Nova Atualização"
                    
                    corpo = soup_int.find('article') or soup_int.find('main')
                    
                    texto_en = ""
                    links_video = []
                    links_imagem = []

                    if corpo:
                        # Extração de texto
                        for p in corpo.find_all('p')[:8]:
                            if len(p.text) > 20: texto_en += p.text + "\n\n"
                        
                        # Extração de Vídeos (Youtube/Shorts/Vimeo)
                        for iframe in corpo.find_all('iframe'):
                            src = iframe.get('src', '')
                            if any(x in src for x in ['youtube.com', 'youtu.be', 'vimeo.com']):
                                video_clean = src.split('?')[0].replace('embed/', 'watch?v=')
                                links_video.append(video_clean)

                        for a in corpo.find_all('a', href=True):
                            href = a['href']
                            if 'youtube.com/shorts/' in href or 'youtu.be/' in href:
                                if href not in links_video: links_video.append(href)

                        # Extração de Imagens
                        for img in corpo.find_all('img'):
                            img_src = img.get('src') or img.get('data-src')
                            if img_src and img_src.startswith('http') and not any(x in img_src for x in ['icon', 'logo']):
                                links_imagem.append(img_src)

                    print(f"📊 Dados coletados: {len(texto_en)} caracteres de texto, {len(links_video)} vídeos, {len(links_imagem)} imagens.")

                    # --- TRADUÇÃO ---
                    tradutor = GoogleTranslator(source='en', target='pt')
                    titulo_pt = tradutor.translate(titulo_en)
                    resumo_pt = tradutor.translate(texto_en[:2000]) if texto_en else "Confira os detalhes no site oficial."

                    # --- POSTAGEM: CANAL NOTÍCIAS ---
                    canal_news = bot.get_channel(CANAL_NOTICIAS_ID)
                    if canal_news:
                        embed = discord.Embed(
                            title=f"🚨 {titulo_pt}",
                            description=f"{resumo_pt}\n\n🔗 [Artigo Original]({url_completa})",
                            color=0x3498db,
                            timestamp=datetime.now()
                        )
                        if links_imagem: embed.set_image(url=links_imagem[0])
                        msg = await canal_news.send(content="@everyone", embed=embed)
                        await msg.add_reaction("🔥")
                        print("📡 Mensagem de texto enviada para o canal de notícias.")

                    # --- POSTAGEM: CANAL MÍDIA ---
                    canal_midia = bot.get_channel(CANAL_MIDIA_ID)
                    if canal_midia and (links_video or len(links_imagem) > 1):
                        await canal_midia.send(f"🎬 **Mídias da Atualização:** *{titulo_pt}*")
                        
                        for vid in links_video:
                            await canal_midia.send(vid)
                            print(f"🎥 Vídeo postado: {vid}")
                        
                        if len(links_imagem) > 1:
                            for img_extra in links_imagem[1:4]:
                                await canal_midia.send(img_extra)
                        print("📸 Mídias extras (vídeos/fotos) enviadas para o canal de mídia.")

        except Exception as e:
            print(f"❌ CRITICAL ERROR NO MONITOR: {e}")

# --- BANCO DE DADOS ---
def get_db_connection():
    if not DATABASE_URL: return None
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1) if DATABASE_URL.startswith("postgres://") else DATABASE_URL
    try: return psycopg2.connect(url, sslmode='require', connect_timeout=10)
    except: return None

def setup_db():
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (id BIGINT PRIMARY KEY, rep INTEGER DEFAULT 0, ultima_rep TIMESTAMP)''')
        # Adicionada a coluna "tipo" (TEXT) para diferenciar Scam de Hack
        cursor.execute('''CREATE TABLE IF NOT EXISTS blacklist (
            user_id BIGINT PRIMARY KEY, 
            motivo TEXT, 
            staff_id BIGINT, 
            tipo TEXT DEFAULT 'scam', 
            data_blacklist TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
        cursor.close()
        conn.close()

def alterar_rep(user_id, quantidade, definir=False):
    conn = get_db_connection()
    if not conn: return 0
    cursor = conn.cursor()
    if definir:
        cursor.execute('INSERT INTO usuarios (id, rep) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET rep = EXCLUDED.rep RETURNING rep', (user_id, quantidade))
    else:
        cursor.execute('INSERT INTO usuarios (id, rep) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET rep = usuarios.rep + EXCLUDED.rep RETURNING rep', (user_id, quantidade))
    res = cursor.fetchone()
    conn.commit()
    cursor.close()
    conn.close()
    return res[0] if res else 0

# --- SISTEMA DE LOGS ---
async def enviar_log(origem, mensagem, cor=0xffa500):
    if LOG_CHANNEL_ID == 0: return
    canal = bot.get_channel(LOG_CHANNEL_ID)
    if canal:
        autor = origem.user if hasattr(origem, 'user') else origem.author
        embed = discord.Embed(title="🛰️ Registro de Atividade", description=mensagem, color=cor, timestamp=datetime.now())
        embed.set_footer(text=f"Executor: {autor.name}")
        await canal.send(embed=embed)

# --- CHECKS (VERIFICAÇÕES) ---
@bot.check
async def verificar_canal(ctx):
    if isinstance(ctx.channel, discord.DMChannel): 
        return False
    
    # Staff/ADM ignora todas as restrições de canal abaixo
    is_admin = ctx.author.guild_permissions.administrator
    is_mod = any(role.name.lower() == "mods" for role in ctx.author.roles)
    
    if is_admin or is_mod:
        return True
    
    # Restrição apenas para usuários comuns
    parent_id = getattr(ctx.channel, "parent_id", None)
    no_forum_troca = (ctx.channel.id == ID_FORUM_TROCA or parent_id == ID_FORUM_TROCA)
    no_canal_raid = (ctx.channel.id == ID_CANAL_RAID)
    
    return no_forum_troca or no_canal_raid

def eh_staff():
    async def predicate(ctx):
        is_mod = any(role.name.lower() == "mods" for role in ctx.author.roles)
        is_admin = ctx.author.guild_permissions.administrator
        if is_mod or is_admin: return True
        await ctx.send("❌ Você não tem permissão para usar este comando.", delete_after=5)
        return False
    return commands.check(predicate)

def ignora_cooldown_staff():
    async def predicate(ctx):
        is_mod = any(role.name.lower() == "mods" for role in ctx.author.roles)
        is_admin = ctx.author.guild_permissions.administrator
        if is_mod or is_admin:
            ctx.command.reset_cooldown(ctx)
        return True
    return commands.check(predicate)

# --- SISTEMA DE CARGOS ---
async def verificar_cargos_nivel(ctx, membro, pontos):
    niveis = [{"limite": 100, "nome": "trocador oficial"}, {"limite": 50, "nome": "trocador confiavel"}, {"limite": 10, "nome": "trocador iniciante"}]
    cargo_perigoso = discord.utils.get(ctx.guild.roles, name="trocador perigoso")
    if pontos <= -10 and cargo_perigoso:
        if cargo_perigoso not in membro.roles: await membro.add_roles(cargo_perigoso)
    elif cargo_perigoso and cargo_perigoso in membro.roles and pontos > -10:
        await membro.remove_roles(cargo_perigoso)
    for nivel in niveis:
        cargo = discord.utils.get(ctx.guild.roles, name=nivel["nome"])
        if cargo:
            if pontos >= nivel["limite"] and cargo not in membro.roles: await membro.add_roles(cargo)
            elif pontos < nivel["limite"] and cargo in membro.roles: await membro.remove_roles(cargo)

# --- CLASSES DE INTERFACE (VIEWS) ---
class FinalizarTrocaView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Finalizar e Excluir Tópico", 
        style=discord.ButtonStyle.secondary, 
        emoji="✅",
        custom_id="btn_finalizar_troca"
    )
    async def finalizar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        thread = interaction.channel
        is_owner = interaction.user.id == thread.owner_id
        is_staff = any(role.name.lower() == "mods" for role in interaction.user.roles) or interaction.user.guild_permissions.administrator

        if not (is_owner or is_staff):
            return await interaction.response.send_message("❌ Apenas o dono do post ou a staff podem finalizar esta troca.", ephemeral=True)

        await interaction.response.send_message("⚠️ **Troca finalizada.** Este tópico será **EXCLUÍDO** permanentemente em 5 segundos..")
        await asyncio.sleep(5)
        
        try:
            nome_topico = thread.name
            await enviar_log(interaction, f"🗑️ **Tópico Excluído**\nPost: `{nome_topico}`\nExecutor: {interaction.user.mention}", 0xe74c3c)
            await thread.delete(reason=f"Finalizado por {interaction.user.name}")
        except discord.Forbidden:
            try: await thread.send("❌ **Erro:** O bot precisa da permissão 'Gerenciar Tópicos' para excluir este canal.")
            except: pass
        except Exception as e:
            print(f"❌ Erro ao excluir tópico: {e}")

class VoiceSelectionView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        canais_voz = [1441884973077495808, 1441885994248044605, 1441887071533928540, 1439303187332071594, 1439314706719445218, 1439314014579593607]
        for i, canal_id in enumerate(canais_voz, 1):
            self.add_item(discord.ui.Button(label=f"Sala {i}", url=f"https://discord.com/channels/{guild_id}/{canal_id}", style=discord.ButtonStyle.link))

class RaidView(discord.ui.View):
    def __init__(self, host, mapa, vagas_totais):
        super().__init__(timeout=3600)
        self.host = host
        self.mapa = mapa
        self.vagas_totais = vagas_totais
        self.participantes = [host]

    @discord.ui.button(label="Entrar no Squad", style=discord.ButtonStyle.green, emoji="✋")
    async def entrar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.participantes) >= self.vagas_totais:
            if interaction.user.id == self.host.id:
                view_voz = VoiceSelectionView(interaction.guild.id)
                return await interaction.response.send_message(content=f"🎮 **Sua Raid de {self.mapa.upper()} está pronta!**\n\n**Como convidar seu squad:**\n1. Escolha uma sala abaixo.\n2. Clique com o botão direito nela e selecione **'Copiar Link'**.\n3. Cole o link aqui no canal para seus parceiros entrarem.", view=view_voz, ephemeral=True)
            else:
                return await interaction.response.send_message("❌ Este squad já está completo!", ephemeral=True)
        if interaction.user in self.participantes:
            return await interaction.response.send_message("❌ Você já está neste squad!", ephemeral=True)
        self.participantes.append(interaction.user)
        embed = interaction.message.embeds[0]
        lista_mentions = "\n".join([m.mention for m in self.participantes])
        embed.set_field_at(1, name=f"Membros ({len(self.participantes)}/{self.vagas_totais})", value=lista_mentions, inline=False)
        if len(self.participantes) >= self.vagas_totais:
            button.label = "Squad Completo (Clique p/ Salas)"
            button.style = discord.ButtonStyle.secondary
            embed.color = discord.Color.gold()
        await interaction.message.edit(embed=embed, view=self)
        if len(self.participantes) >= self.vagas_totais and interaction.user.id == self.host.id:
            await interaction.response.send_message(content="✅ **Squad Completo!** Escolha a sala abaixo e envie o link.", view=VoiceSelectionView(interaction.guild.id), ephemeral=True)
        else:
            await interaction.response.send_message("✅ Você entrou no squad!", ephemeral=True)

# --- COMANDOS ---
@bot.command()
async def ajuda(ctx):
    # Tenta apagar a mensagem do usuário para limpar o chat
    try: await ctx.message.delete()
    except: pass

    embed = discord.Embed(
        title="🛰️ TERMINAL DE SUPORTE - ARC RAIDERS BRASIL",
        description=(
            "Bem-vindo ao sistema de auxílio automatizado. Abaixo estão os protocolos disponíveis para todos os raiders.\n\n"
            "**PS:** Comandos de troca funcionam apenas no canal de trocas."
        ),
        color=0x3498db # Azul tático
    )

    # --- CATEGORIA: SOBREVIVÊNCIA & TROCAS ---
    embed.add_field(
        name="📦 SISTEMA DE TROCAS",
        value=(
            "🌟 `/rep @membro` - Dá +1 de reputação positiva.\n"
            "💢 `/neg @membro` - Dá -1 de reputação negativa.\n"
            "👤 `/perfil @membro` - Consulta a ficha e o status do raider.\n"
            "🏆 `/top` - Exibe os 10 raiders mais confiáveis para trocas.\n\n"
        ),
        inline=False
    )

    # --- CATEGORIA: SQUAD & EXPLORAÇÃO ---
    embed.add_field(
        name="📡 COMUNICAÇÃO DE RAID",
        value=(
            "🚨 `/raid [mapa] 1` - Abre chamada para **DUO**.\n"
            "🚨 `/raid [mapa] 2` - Abre chamada para **TRIO**.\n\n"
        ),
        inline=False
    )

    # --- CATEGORIA: STAFF (SÓ APARECE SE FOR MOD/ADM) ---
    is_mod = any(role.name.lower() == "mods" for role in ctx.author.roles)
    is_admin = ctx.author.guild_permissions.administrator

    if is_mod or is_admin:
        embed.add_field(
            name="🛠️ PROTOCOLOS DE COMANDO (STAFF)",
            value=(
                "📢 `/falar [texto/embed] [msg]` - Anúncios oficiais.\n"
                "🧹 `/limpar [n]` - Faxina rápida no canal.\n"
                "🚨 `/denunciar @membro [tipo] [motivo]` - Blacklist global.\n"
                "📜 `/setrep @membro [pontos]` - Alterar reputação de algum raider.\n"
                "⚙️ `/status` - Saúde do banco de dados e do bot.\n\n"
            ),
            inline=False
        )

    # Identidade Visual
    if ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)
    
    embed.set_footer(
        text=f"Developer: {ctx.author.name} | Sponsor: ! Gio • ARC Raiders Brasil", 
        icon_url=ctx.author.display_avatar.url
    )

    # Envia a ajuda apenas para quem pediu (evita flood no chat geral)
    # Ou retire o 'delete_after' se preferir que fique fixo
    await ctx.send(embed=embed, delete_after=60)

@bot.command()
async def raid(ctx, mapa: str = None, vagas: int = None):
    if mapa is None or vagas is None:
        return await ctx.send("❌ Uso: `/raid [mapa/objetivo] [vagas]` (1 para Duo, 2 para Trio)")
    if ctx.channel.id != ID_CANAL_RAID:
        return await ctx.send(f"❌ Use em <#{ID_CANAL_RAID}>.", delete_after=5)
    if vagas < 1 or vagas > 2:
        return await ctx.send("❌ Escolha 1 ou 2 vagas extras.")
    total = vagas + 1
    embed = discord.Embed(title=f"🚨Chamada p/ Raid: {'DUO' if total==2 else 'TRIO'}", color=0x2ecc71)
    embed.add_field(name="📍 Mapa/Objetivo", value=mapa.upper(), inline=True)
    embed.add_field(name=f"Membros (1/{total})", value=f"👤 {ctx.author.mention}", inline=False)
    await ctx.send(embed=embed, view=RaidView(ctx.author, mapa, total))

@bot.command()
async def top(ctx):
    conn = get_db_connection()
    if not conn: return await ctx.send("❌ Erro no banco de dados.")
    cursor = conn.cursor()
    cursor.execute('SELECT id, rep FROM usuarios ORDER BY rep DESC LIMIT 10')
    usuarios = cursor.fetchall()
    conn.close()
    if not usuarios: return await ctx.send("⚠️ O ranking ainda está vazio.")
    descricao = ""
    for i, (uid, pontos) in enumerate(usuarios, 1):
        user = bot.get_user(uid)
        nome = user.name if user else f"Usuário Antigo ({uid})"
        prefixo = "🥇 " if i == 1 else "🥈 " if i == 2 else "🥉 " if i == 3 else f"**{i}.** "
        descricao += f"{prefixo}{nome} — `{pontos} pts` \n"
    embed = discord.Embed(title="🏆 Top 10 - Maiores Reputações", description=descricao, color=0xf1c40f, timestamp=datetime.now())
    embed.set_footer(text="ARC Raiders Brasil | Ranking de Confiança")
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 7200, commands.BucketType.user)
@ignora_cooldown_staff()
async def rep(ctx, membro: discord.Member):
    if membro.id == ctx.author.id:
        ctx.command.reset_cooldown(ctx)
        return await ctx.send("❌ Você não pode dar reputação para si mesmo.")
    
    if membro.bot:
        ctx.command.reset_cooldown(ctx)
        return await ctx.send("❌ Bots não possuem reputação.")

    try:
        nova = alterar_rep(membro.id, 1)
        if nova is not None:
            await ctx.send(f"🌟 {ctx.author.mention} deu +1 rep para {membro.mention}!")
            await enviar_log(ctx, f"🌟 **Reputação Positiva**\nPara: {membro.mention}\nTotal: `{nova}`", 0x2ecc71)
            await verificar_cargos_nivel(ctx, membro, nova)
        else:
            ctx.command.reset_cooldown(ctx)
            await ctx.send("❌ Erro ao salvar no banco de dados. Verifique a conexão.")
    except Exception as e:
        print(f"Erro no comando !rep: {e}")
        ctx.command.reset_cooldown(ctx)
        await ctx.send("❌ Ocorreu um erro interno ao processar a reputação.")

@bot.command()
@commands.cooldown(1, 7200, commands.BucketType.user)
@ignora_cooldown_staff()
async def neg(ctx, membro: discord.Member):
    if membro.id == ctx.author.id or membro.bot:
        ctx.command.reset_cooldown(ctx)
        return await ctx.send("❌ Comando inválido.")
    nova = alterar_rep(membro.id, -1)
    await ctx.send(f"💢 {ctx.author.mention} deu -1 rep para {membro.mention}!")
    await enviar_log(ctx, f"💢 **Reputação Negativa**\nPara: {membro.mention}\nTotal: `{nova}`", 0xe74c3c)
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
async def perfil(ctx, membro: discord.Member = None):
    membro = membro or ctx.author
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT rep FROM usuarios WHERE id = %s', (membro.id,))
    res_rep = cursor.fetchone()
    pontos = res_rep[0] if res_rep else 0
    
    # Busca o motivo e o TIPO do banimento
    cursor.execute('SELECT motivo, tipo FROM blacklist WHERE user_id = %s', (membro.id,))
    res_black = cursor.fetchone()
    conn.close()

    if res_black:
        motivo, tipo = res_black
        cor = 0x000000 if tipo == 'hack' else 0xff0000 # Preto para hack, vermelho para scam
        titulo = "🛑 PERFIL BLOQUEADO: HACKER 🛑" if tipo == 'hack' else "⚠️ RISCO: SCAMMER ⚠️"
        
        embed = discord.Embed(title=titulo, color=cor)
        embed.description = f"🚨 **ESTE USUÁRIO FOI DENUNCIADO!**\n\n**Tipo de Infração:** `{tipo.upper()}`\n**Motivo:** {motivo}"
        embed.add_field(name="Status", value="BANIDO DA COMUNIDADE", inline=True)
    else:
        # Lógica normal de trocador (mantém seu código atual aqui)
        status = "Neutro"
        if pontos >= 100: status = "Trocador Oficial 💎"
        elif pontos >= 50: status = "Trocador Confiável ✅"
        elif pontos >= 10: status = "Trocador Iniciante ✅"
        elif pontos <= -10: status = "Trocador Perigoso ❌"
        
        embed = discord.Embed(title=f"Perfil de {membro.name}", color=0x2ecc71)
        embed.add_field(name="Pontos de Reputação", value=f"`{pontos}`", inline=True)
        embed.add_field(name="Status", value=status, inline=True)

    embed.set_thumbnail(url=membro.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command()
@eh_staff()
async def setrep(ctx, membro: discord.Member, valor: int):
    nova = alterar_rep(membro.id, valor, definir=True)
    await ctx.send(f"✅ Rep de {membro.mention} definida para `{valor}`.")
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
@eh_staff()
async def resetar(ctx, membro: discord.Member):
    nova = alterar_rep(membro.id, 0, definir=True)
    await ctx.send(f"♻️ A reputação de {membro.mention} foi resetada para 0.")
    await enviar_log(ctx, f"♻️ **Reset de Reputação**\nAlvo: {membro.mention}", 0x95a5a6)
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command(aliases=['clear', 'purge'])
@eh_staff()
async def limpar(ctx, quantidade: int = None):
    # Verifica se a quantidade foi informada
    if quantidade is None:
        return await ctx.send("❌ Uso correto: `/limpar [quantidade]` (ex: `!limpar 10`)", delete_after=5)

    # Limite de segurança para evitar abusos ou bugs do Discord
    if quantidade < 1 or quantidade > 100:
        return await ctx.send("❌ Podes limpar entre 1 e 100 mensagens de cada vez.", delete_after=5)

    try:
        # O purge apaga as mensagens. O +1 é para apagar também a mensagem do comando !limpar
        deleted = await ctx.channel.purge(limit=quantidade + 1)
        
        # Envia uma confirmação que será apagada em 5 segundos
        confirmacao = await ctx.send(f"🧹 **Faxina concluída!** `{len(deleted)-1}` mensagens foram removidas.")
        
        # Regista a ação nos logs do servidor
        await enviar_log(ctx, f"🧹 **Limpeza de Chat**\n**Canal:** {ctx.channel.mention}\n**Quantidade:** {len(deleted)-1} mensagens.", 0x3498db)
        
        await asyncio.sleep(5)
        await confirmacao.delete()
        
    except discord.Forbidden:
        await ctx.send("❌ Erro: Eu não tenho permissão para 'Gerenciar Mensagens'.")
    except Exception as e:
        print(f"Erro no comando limpar: {e}")
        await ctx.send(f"❌ Ocorreu um erro ao tentar limpar o chat.")

@bot.command()
@eh_staff()
async def status(ctx):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Conta usuários e blacklist
    cursor.execute('SELECT COUNT(*) FROM usuarios')
    total_users = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM blacklist')
    total_black = cursor.fetchone()[0]
    conn.close()
    
    membros_totais = ctx.guild.member_count
    
    embed = discord.Embed(title="📊 Status do Setor", color=0x2ecc71)
    embed.add_field(name="👥 Membros no Servidor", value=f"`{membros_totais}`", inline=True)
    embed.add_field(name="🗄️ Registos no DB", value=f"`{total_users}`", inline=True)
    embed.add_field(name="🚫 Raiders na Blacklist", value=f"`{total_black}`", inline=True)
    embed.set_footer(text=f"Latência: {round(bot.latency * 1000)}ms")
    
    await ctx.send(embed=embed)

@bot.command(aliases=['warn'])
@eh_staff()
async def avisar(ctx, membro: discord.Member, *, motivo: str = "Não especificado"):
    if membro.bot:
        return await ctx.send("❌ Não podes avisar bots.")
    
    embed = discord.Embed(title="⚠️ Advertência de Staff", color=0xffa500)
    embed.add_field(name="Raider Avisado", value=membro.mention, inline=True)
    embed.add_field(name="Staff", value=ctx.author.mention, inline=True)
    embed.add_field(name="Motivo", value=motivo, inline=False)
    embed.set_footer(text="Por favor, mantenha a ordem na comunidade!")
    
    await ctx.send(content=membro.mention, embed=embed)
    
    # Envia para os logs
    await enviar_log(ctx, f"⚠️ **Warn Aplicado**\n**Alvo:** {membro.mention}\n**Motivo:** {motivo}", 0xffa500)
    
    try:
        await membro.send(f"Olá {membro.name}, você recebeu um aviso oficial no **ARC Raiders Brasil**.\n**Motivo:** {motivo}")
    except:
        pass # Ignora se o DM do usuário estiver fechado

@bot.command()
@eh_staff()
async def colocar_botao(ctx):
    if isinstance(ctx.channel, discord.Thread):
        await ctx.send("Clique abaixo para finalizar esta troca:", view=FinalizarTrocaView())
    else:
        await ctx.send("Este comando só funciona dentro de um tópico!")

@bot.command(aliases=['say', 'say2', 'anuncio'])
@eh_staff()
async def falar(ctx, tipo: str, *, mensagem: str = None):
    # 1. Verifica se há conteúdo ou imagem
    tem_anexo = len(ctx.message.attachments) > 0
    if not mensagem and not tem_anexo:
        return await ctx.send("❌ Digite uma mensagem ou anexe uma imagem!", delete_after=10)

    tipo = tipo.lower()
    
    # Prepara o arquivo para re-envio (evita que o link quebre ao deletar a msg)
    arquivo_copy = None
    if tem_anexo:
        arquivo_copy = await ctx.message.attachments[0].to_file()

    # 3. Apaga o comando original
    try: await ctx.message.delete()
    except: pass

    # --- MODO TEXTO ---
    if tipo == "texto":
        texto_final = f"{mensagem if mensagem else ''}\n_Enviado por: {ctx.author.mention}_"
        await ctx.send(content=texto_final, file=arquivo_copy)
        await enviar_log(ctx, f"📢 **Msg Texto** em {ctx.channel.mention}", 0x9b59b6)

    # --- MODO EMBED ---
    elif tipo == "embed":
        if mensagem and '"' in mensagem:
            partes = mensagem.split('"', 2)
            titulo = partes[1]
            conteudo = partes[2].strip()
        else:
            titulo = "Informativo ARC Raiders Brasil"
            conteudo = mensagem if mensagem else ""

        embed = discord.Embed(title=f"📢 {titulo}", description=conteudo, color=0xf1c40f)
        
        if ctx.guild.icon:
            embed.set_author(name="Comunidade ARC Raiders Brasil", icon_url=ctx.guild.icon.url)
        
        embed.set_footer(text=f"Staff: {ctx.author.name}", icon_url=ctx.author.display_avatar.url)

        # Se tiver imagem, anexamos o arquivo e referenciamos no Embed
        if arquivo_copy:
            # O nome do arquivo no anexo deve ser o mesmo usado no set_image
            embed.set_image(url=f"attachment://{arquivo_copy.filename}")
            await ctx.send(content="@everyone", embed=embed, file=arquivo_copy)
        else:
            await ctx.send(content="@everyone", embed=embed)
            
        await enviar_log(ctx, f"📢 **Anúncio Embed** em {ctx.channel.mention}\nTítulo: {titulo}", 0xf1c40f)

    else:
        await ctx.send("❌ Escolha `texto` ou `embed`.", delete_after=10)

@bot.command()
@eh_staff()
async def denunciar(ctx, membro: discord.Member, tipo: str, *, motivo: str):
    # Padroniza o tipo
    tipo = tipo.lower()
    if tipo not in ['scam', 'hack', 'outros']:
        return await ctx.send("❌ Tipo inválido! Use: `scam`, `hack` ou `outros`.\nEx: `/denunciar @membro hack Usou aimbot na extração`")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO blacklist (user_id, motivo, staff_id, tipo) 
            VALUES (%s, %s, %s, %s) 
            ON CONFLICT (user_id) DO UPDATE SET motivo = EXCLUDED.motivo, tipo = EXCLUDED.tipo
        ''', (membro.id, motivo, ctx.author.id, tipo))
        
        conn.commit()
        alterar_rep(membro.id, -999, definir=True)

        # Embed customizada dependendo do crime
        cor = 0xff0000 if tipo == 'hack' else 0xe67e22
        emoji = "🚫" if tipo == 'hack' else "📦"
        
        embed = discord.Embed(title=f"{emoji} Raider Banido: {tipo.upper()}", color=cor)
        embed.add_field(name="Membro", value=membro.mention, inline=True)
        embed.add_field(name="Staff", value=ctx.author.mention, inline=True)
        embed.add_field(name="Motivo", value=motivo, inline=False)
        embed.set_footer(text="Segurança ARC Raiders Brasil")
        
        await ctx.send(embed=embed)
        await enviar_log(ctx, f"🚨 **BLACK-LIST GLOBAL**\n**Alvo:** {membro.mention}\n**Tipo:** {tipo}\n**Motivo:** {motivo}", cor)
        
    except Exception as e: 
        await ctx.send(f"❌ Erro ao processar denúncia: {e}")
    finally: 
        conn.close()

@bot.command()
@eh_staff()
async def perdoar(ctx, membro: discord.Member):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM blacklist WHERE user_id = %s', (membro.id,))
    conn.commit()
    conn.close()
    await ctx.send(f"✅ {membro.mention} foi removido da lista negra.")
    await enviar_log(ctx, f"🛡️ **PERDÃO**\nAlvo: {membro.mention} removido da blacklist.", 0x2ecc71)

@bot.command()
@eh_staff()
async def backup(ctx):
    await ctx.send("📂 Gerando backup...")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, rep FROM usuarios ORDER BY rep DESC')
        usuarios = cursor.fetchall()
        cursor.execute('SELECT user_id, motivo FROM blacklist')
        blacklisted = cursor.fetchall()
        conn.close()
        buffer = io.StringIO()
        buffer.write(f"--- BACKUP ARC RAIDERS BRASIL ({datetime.now().strftime('%d/%m/%Y %H:%M')}) ---\n\n🌟 RANKING:\n")
        for uid, pts in usuarios:
            u = bot.get_user(uid)
            buffer.write(f"ID: {uid} | Nome: {u.name if u else 'Desconhecido'} | Pts: {pts}\n")
        buffer.write("\n🚫 BLACKLIST:\n")
        for uid, mot in blacklisted:
            u = bot.get_user(uid)
            buffer.write(f"ID: {uid} | Nome: {u.name if u else 'Desconhecido'} | Motivo: {mot}\n")
        buffer.seek(0)
        await ctx.send(content="✅ Backup concluído:", file=discord.File(fp=buffer, filename=f"backup_{datetime.now().strftime('%d_%m_%Y')}.txt"))
    except Exception as e: await ctx.send(f"❌ Erro: {e}")

@bot.command()
@eh_staff()
async def postar_regras(ctx):
    """Posta o mural de regras com o botão de verificação."""
    try: await ctx.message.delete()
    except: pass

    embed = discord.Embed(
        title="🛰️ DIRETRIZES DA COMUNIDADE - ARC RAIDERS BRASIL",
        description=(
            "Bem-vindo à Resistência! Para garantir uma convivência tática e justa, siga as normas:\n\n"
            "**1. RESPEITO ACIMA DE TUDO**\n"
            "Sem toxicidade, racismo, homofobia ou qualquer tipo de preconceito. Somos um comunidade.\n\n"
            "**2. PROIBIDO RMT (Real Money Trade)**\n"
            "Compra e venda de itens ou contas por dinheiro real é terminantemente proibida. Sujeito a banimento imediato.\n\n"
            "**3. TRAPAÇAS E HACKS**\n"
            "O uso de softwares de terceiros (Aimbot, Wallhack, etc) resultará em blacklist global no servidor e denunciado para os devs. Também não é permitido, mencionar o uso de qualquer um dos itens acima ou compartilhar links para acessar esse tipo de conteúdo.\n\n"
            "**4. CANAIS DE TROCA**\n"
            "Use o sistema de reputação (`/rep`/`/neg`) para manter a segurança da comunidade.\n\n"
            "**5. CONDUTA EM RAID**\n"
            "Seja um bom parceiro. Abandonar o squad propositalmente ou 'trollar' extrações gera má reputação.\n\n"
            "**6. SEM PUBLICIDADE**\n"
            "Não é permitido publicar links, imagens ou mensagens que contenham ou se relacionem a anúncios. Isso inclui links/códigos de indicação, convites para servidores e promoção em redes sociais Existem canais e cargos para certas divulgações.\n\n"
            "**7. SEM DISCUSSÕES POLARIZADAS OU INTENCIONALMENTE CONTROVERSAS**\n"
            "Não inicie conversas com a intenção de causar conflito ou indignação. Evite tópicos fortemente polarizadores, como alinhamento político ou crenças religiosas.\n\n"
            "**As regras acima não são exaustivas. Administradores e moderadores usarão seu bom senso ao lidar com comportamentos perturbadores.** \n\n"
            "**Ao clicar no botão abaixo, você confirma que leu e concorda com as regras.**"
        ),
        color=0x2ecc71
    )
    
    if ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)
    
    embed.set_footer(text="Segurança ARC Raiders Brasil", icon_url=bot.user.display_avatar.url)
    
    await ctx.send(embed=embed, view=RegrasView())

@bot.command()
@eh_staff()
async def postar_suporte(ctx):
    """Posta o painel de abertura de tickets."""
    try: await ctx.message.delete()
    except: pass

    embed = discord.Embed(
        title="📩 Precisa de ajuda ou denunciar algo?",
        description=(
            "Clique no botão abaixo para abrir um canal de atendimento privado com a nossa staff.\n\n"
            "**O que você pode tratar aqui:**\n"
            "• Denúncias de hackers/scammers.\n"
            "• Denúncias sobre má conduta ou quebra de regra.\n"
            "• Dúvidas gerais sobre a comunidade.\n\n"
            "*Evite abrir tickets sem necessidade.*"
        ),
        color=0x3498db
    )
    await ctx.send(embed=embed, view=AbrirTicketView())

# --- EVENTOS ---
@bot.event
async def on_ready():
    setup_db()
    # Registrando todas as views persistentes
    bot.add_view(FinalizarTrocaView()) 
    bot.add_view(RegrasView())
    bot.add_view(AbrirTicketView())
    bot.add_view(TicketControlView())
    if not monitorar_noticias_pro.is_running():
        monitorar_noticias_pro.start()
    if not manter_banco_vivo.is_running():
        manter_banco_vivo.start()
    print(f"✅ {bot.user.name} Bot Online!")
    await bot.change_presence(activity=discord.Game(name="/ajuda | ARC Raiders Brasil"))

class RegrasView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Sem timeout para o botão não parar de funcionar

    @discord.ui.button(label="Aceitar e Entrar", style=discord.ButtonStyle.green, emoji="✅", custom_id="btn_aceitar_regras")
    async def aceitar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # NOME DO CARGO: Mude para o nome do cargo inicial do seu servidor
        nome_cargo = "speranza" 
        cargo = discord.utils.get(interaction.guild.roles, name=nome_cargo)

        if not cargo:
            return await interaction.response.send_message(f"❌ Erro: O cargo `{nome_cargo}` não existe no servidor. Avise a Staff!", ephemeral=True)

        if cargo in interaction.user.roles:
            return await interaction.response.send_message("✅ Você já aceitou as regras e já é um cidadão de Speranza!", ephemeral=True)

        try:
            await interaction.user.add_roles(cargo)
            await interaction.response.send_message(f"🚀 Bem-vindo ao fronte, {interaction.user.name}! Você agora é um cidadão de **{nome_cargo}**. Cuidado com os ARC's, outros raiders e boa sorte na extração!", ephemeral=True)
            # Log opcional
            await enviar_log(interaction, f"✅ **Novo Membro**\n{interaction.user.mention} aceitou as regras.", 0x2ecc71)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Eu não tenho permissão para dar cargos. Verifique minha posição na lista de cargos!", ephemeral=True)

class MotivoFecharTicketModal(discord.ui.Modal, title='Encerrar Atendimento'):
    motivo = discord.ui.TextInput(
        label='Motivo do fechamento',
        style=discord.TextStyle.paragraph,
        placeholder='Ex: Dúvida tirada / Jogador banido por cheat / Spam...',
        required=True,
        min_length=5,
        max_length=300
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("🔒 Gerando transcrição e encerrando ticket...", ephemeral=True)
        
        canal_ticket = interaction.channel
        
        # --- GERAR TRANSCRIÇÃO ---
        log_content = f"--- TRANSCRIÇÃO DE TICKET: {canal_ticket.name} ---\n"
        log_content += f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
        log_content += f"Fechado por: {interaction.user.name}\n"
        log_content += f"MOTIVO: {self.motivo.value}\n" # <--- O motivo do Pop-up entra aqui
        log_content += "------------------------------------------\n\n"

        async for msg in canal_ticket.history(limit=500, oldest_first=True):
            timestamp = msg.created_at.strftime('%d/%m/%Y %H:%M')
            log_content += f"[{timestamp}] {msg.author.name}: {msg.content}\n"
            if msg.attachments:
                for att in msg.attachments:
                    log_content += f"   > Anexo: {att.url}\n"

        buffer = io.BytesIO(log_content.encode('utf-8'))
        arquivo_log = discord.File(fp=buffer, filename=f"log_{canal_ticket.name}.txt")

        # Log no canal de monitoramento
        await enviar_log(interaction, f"🔒 **Ticket Encerrado**\nCanal: `{canal_ticket.name}`\nExecutor: {interaction.user.mention}\n**Motivo:** {self.motivo.value}", 0xe74c3c)
        
        canal_logs = bot.get_channel(LOG_CHANNEL_ID)
        if canal_logs:
            await canal_logs.send(content=f"📄 Transcrição completa do ticket `{canal_ticket.name}`:", file=arquivo_log)

        await asyncio.sleep(3)
        await canal_ticket.delete()

class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Fechar Ticket", style=discord.ButtonStyle.secondary, emoji="🔒", custom_id="btn_fechar_ticket")
    async def fechar_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Verifica se é Staff
        is_staff = any(role.name.lower() == "mods" for role in interaction.user.roles) or interaction.user.guild_permissions.administrator
        
        if not is_staff:
            return await interaction.response.send_message("❌ Apenas a staff pode encerrar tickets.", ephemeral=True)
            
        # Chama o Pop-up (Modal)
        await interaction.response.send_modal(MotivoFecharTicketModal())

class AbrirTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Abrir Ticket / Denúncia", style=discord.ButtonStyle.primary, emoji="📩", custom_id="btn_abrir_ticket")
    async def abrir_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user
        id_categoria_ticket = 1432701386738499666
        
        # Nome do canal do ticket
        nome_canal = f"ticket-{user.name}".lower()
        
        # Verifica se já existe um ticket aberto para esse user
        existente = discord.utils.get(guild.channels, name=nome_canal)
        if existente:
            return await interaction.response.send_message(f"❌ Você já possui um ticket aberto em {existente.mention}!", ephemeral=True)

        # Configura as permissões do canal
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        # Adiciona permissão para o cargo "mods"
        cargo_mod = discord.utils.get(guild.roles, name="mods")
        if cargo_mod:
            overwrites[cargo_mod] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        # Busca a categoria pelo ID
        categoria = guild.get_channel(id_categoria_ticket)

        try:
            # Cria o canal DENTRO da categoria
            ticket_channel = await guild.create_text_channel(
                nome_canal, 
                overwrites=overwrites, 
                category=categoria,
                reason=f"Ticket aberto por {user.name}"
            )
            
            await interaction.response.send_message(f"✅ Ticket criado! Siga para {ticket_channel.mention}", ephemeral=True)
            
            # Embed inicial dentro do ticket
            embed = discord.Embed(
            title="🛰️ Central de Suporte - ARC Raiders Brasil",
            description=(
                f"Olá {user.mention}, favor ler abaixo e explicar a sua situação.\n\n"
                "*Caso tenha aberto o ticket por engano favor informar.* \n"
                "*Para denúncias:** Informar o ocorrido, enviar prints/vídeos e o ID (discord) do suspeito.* \n"
                "*Para bugs/suporte ao jogo: Logue com sua Embark ID e abra um ticket no link:* https://id.embark.games/pt-BR/arc-raiders/support \n\n"
                "Para as denúncias, as medidas serão tomadas apenas caso tenha provas consistentes e concretas sobre o assunto abordado. \n"
                "Aguarde um membro da staff entrar em contato."
                ),
                color=0x3498db
            )
            embed.set_footer(text="Use o botão abaixo para encerrar o atendimento.")
            
            # Menciona os mods para eles receberem notificação no novo ticket
            mencao_staff = f" <@&{cargo_mod.id}>" if cargo_mod else ""
            await ticket_channel.send(content=f"{user.mention} | {mencao_staff}", embed=embed, view=TicketControlView())

        except Exception as e:
            await interaction.response.send_message(f"❌ Erro ao criar ticket: {e}", ephemeral=True)

@bot.event
async def on_voice_state_update(member, before, after):
    # Log de teste para ver se o bot está ouvindo o evento
    if after.channel:
        print(f"DEBUG: {member.name} entrou no canal {after.channel.name} (ID: {after.channel.id})")

    # --- 1. DETECÇÃO DE ENTRADA NOS HUBS ---
    if after.channel and after.channel.id in [ID_HUB_DUO, ID_HUB_TRIO]:
        print(f"🛰️ GATILHO ATIVADO: Criando canal para {member.name}...")
        guild = member.guild
        
        if after.channel.id == ID_HUB_DUO:
            categoria_alvo = guild.get_channel(ID_CAT_DUO)
            limite, prefixo = 2, "🛰️ DUO"
        else:
            categoria_alvo = guild.get_channel(ID_CAT_TRIO)
            limite, prefixo = 3, "🛸 TRIO"

        if not categoria_alvo:
            print(f"❌ ERRO: Categoria não encontrada! Verifique o ID.")
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=True),
            member: discord.PermissionOverwrite(manage_channels=True, move_members=True, manage_permissions=True, connect=True),
            guild.me: discord.PermissionOverwrite(manage_channels=True, connect=True, move_members=True)
        }

        try:
            novo_canal = await guild.create_voice_channel(
                name=f"{prefixo}: {member.name}",
                category=categoria_alvo,
                user_limit=limite,
                overwrites=overwrites
            )
            print(f"✅ Canal {novo_canal.name} criado com sucesso!")
            await member.move_to(novo_canal)
            print(f"➡️ {member.name} movido para o novo canal.")
        except Exception as e:
            print(f"❌ ERRO AO CRIAR/MOVER: {e}")

    # --- 2. LIMPEZA ---
    if before.channel and before.channel.category_id in [ID_CAT_DUO, ID_CAT_TRIO]:
        if before.channel.id not in [ID_HUB_DUO, ID_HUB_TRIO]:
            if len(before.channel.members) == 0:
                try:
                    await before.channel.delete()
                    print(f"🧹 Canal {before.channel.name} deletado (vazio).")
                except: pass

@bot.event
async def on_thread_create(thread):
    await asyncio.sleep(2)
    # 1. Checa Blacklist
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT motivo FROM blacklist WHERE user_id = %s', (thread.owner_id,))
    blacklisted = cursor.fetchone()
    conn.close()

    if blacklisted:
        await thread.send(f"🚨 **ALERTA DE SEGURANÇA** 🚨\n{thread.owner.mention}, você está na **LISTA NEGRA** e não pode trocar.\n**Motivo:** {blacklisted[0]}")
        await thread.edit(locked=True, archived=True)
        return

    # 2. Envia Boas-vindas e Botão se for no fórum de trocas
    if thread.parent_id == ID_FORUM_TROCA:
        try:
            embed = discord.Embed(
                title="📦 Nova Troca Iniciada!",
                description=(
                    f"Olá {thread.owner.mention}, bem-vindo ao sistema de trocas!\n\n"
                    "**Dicas de Segurança:**\n"
                    "1. Verifique a reputação de alguém usando o comando `/perfil @membro` antes fazer uma troca.\n"
                    "2. Use o comando `/rep @membro` apenas após a troca ser concluída com sucesso.\n"
                    "3. Após finalizada a troca, clique abaixo no botão para finalizar e excluir o tópico.\n"
                    "4. Se por acaso for scammado, abra um ticket acionando nossos mods imediatamente e use o comando `/neg @membro` para negativar o raider.\n\n"
                    "***RMT: Compra e venda de itens com dinheiro real é PROIBIDO e passivo de banimento aqui e no jogo, cuida.***\n\n"
                ),
                color=discord.Color.blue()
            )
            embed.set_footer(text="ARC Raiders Brasil - Sistema de Trocas e Reputação")
            await thread.send(embed=embed, view=FinalizarTrocaView())
            print(f"✅ Botão enviado no tópico: {thread.name}")
        except Exception as e: print(f"❌ Erro thread: {e}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Aguarde {int(error.retry_after // 60)} minutos.", delete_after=10)
    elif isinstance(error, commands.CheckFailure):
        if not ctx.author.guild_permissions.administrator:
             await ctx.send(f"❌ {ctx.author.mention}, este comando não pode ser usado aqui.", delete_after=7)

@tasks.loop(minutes=10)
async def manter_banco_vivo():
    try:
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            conn.close()
            print("ping no banco: OK")
    except Exception as e: print(f"Erro ping banco: {e}")

if __name__ == "__main__":
    setup_db()
    bot.run(TOKEN)