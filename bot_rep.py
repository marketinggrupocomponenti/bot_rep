import os
import sys
import discord
from discord.ext import commands, tasks
import psycopg2
from dotenv import load_dotenv
import requests
from datetime import datetime
import io
import asyncio

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
ID_CANAL_EVENTOS = 1455200454173790208
ID_FORUM_TROCA = 1434310955004592360
ID_CANAL_STAFF = 1412423356946317350
ID_CANAL_RAID = 1412423357600632922

if not TOKEN:
    print("❌ ERRO: DISCORD_TOKEN não encontrado!")
    sys.exit(1)

# --- CONFIGURAÇÃO DO BOT ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

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
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS blacklist (
        user_id BIGINT PRIMARY KEY,
        motivo TEXT,
        staff_id BIGINT,
        data_blacklist TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
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
async def enviar_log(ctx, mensagem, cor=0xffa500):
    if LOG_CHANNEL_ID == 0: return
    canal = bot.get_channel(LOG_CHANNEL_ID)
    if canal:
        embed = discord.Embed(title="🛰️ Registro de Atividade", description=mensagem, color=cor, timestamp=datetime.now())
        embed.set_footer(text=f"Executor: {ctx.author.name}")
        await canal.send(embed=embed)

# --- CHECKS (VERIFICAÇÕES) ---
@bot.check
async def verificar_canal(ctx):
    if isinstance(ctx.channel, discord.DMChannel): 
        return False
    
    is_admin = ctx.author.guild_permissions.administrator
    is_mod = any(role.name.lower() == "mods" for role in ctx.author.roles)
    parent_id = getattr(ctx.channel, "parent_id", None)
    
    no_forum_troca = (ctx.channel.id == ID_FORUM_TROCA or parent_id == ID_FORUM_TROCA)
    no_canal_staff = (ctx.channel.id == ID_CANAL_STAFF)
    no_canal_raid = (ctx.channel.id == ID_CANAL_RAID)

    # Regra unificada
    if is_admin or is_mod:
        return no_forum_troca or no_canal_staff or no_canal_raid
    
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

# ALERTA EVENTOS 
eventos_anunciados = set()

@tasks.loop(minutes=5)
async def monitorar_eventos():
    canal = bot.get_channel(ID_CANAL_EVENTOS)
    if not canal: return
    try:
        response = requests.get("https://metaforge.app/api/arc-raiders/events-schedule", timeout=10)
        if response.status_code == 200:
            dados = response.json()
            eventos = dados.get('events', [])
            for ev in eventos:
                ev_id = ev.get('id')
                if ev.get('is_active') and ev_id not in eventos_anunciados:
                    mapa = ev.get('map_name', 'Desconhecido').upper()
                    nome_evento = ev.get('event_name', 'Operação Padrão')
                    descricao = ev.get('description', 'Fique atento aos perigos!')
                    embed = discord.Embed(title=f"⚠️ ALERTA: {nome_evento}", description=f"**Setor:** {mapa}\n\n{descricao}", color=0xffa500)
                    embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/564/564619.png")
                    await canal.send(content="🚨 **Novo evento detectado!**", embed=embed)
                    eventos_anunciados.add(ev_id)
            if len(eventos_anunciados) > 50: eventos_anunciados.clear()
    except Exception as e: print(f"Erro eventos: {e}")

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

@bot.event
async def on_ready():
    setup_db()
    
    # Inicia os loops apenas se não estiverem rodando
    if not monitorar_eventos.is_running():
        monitorar_eventos.start()
        
    if not manter_banco_vivo.is_running():
        manter_banco_vivo.start()
        
    print(f"✅ {bot.user.name} está ONLINE!")
    print(f"📡 Monitorando eventos em: {ID_CANAL_NOTICIAS}")
    await bot.change_presence(activity=discord.Game(name="!ajuda | ARC Raiders Brasil"))

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

# --- SISTEMA DE RAID (UI) ---
class VoiceSelectionView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        canais_voz = [1441884973077495808, 1441885994248044605, 1441887071533928540, 1439303187332071594, 1439314706719445218, 1439314014579593607]
        for i, canal_id in enumerate(canais_voz, 1):
            self.add_item(discord.ui.Button(label=f"Sala {i}", url=f"https://discord.com/channels/{guild_id}/{canal_id}", style=discord.ButtonStyle.link))

class RaidView(discord.ui.View):
    def __init__(self, host, mapa, vagas_totais):
        super().__init__(timeout=3600)
        self.host, self.mapa, self.vagas_totais = host, mapa, vagas_totais
        self.participantes = [host]

    @discord.ui.button(label="Entrar no Squad", style=discord.ButtonStyle.green, emoji="✋")
    async def entrar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.participantes:
            return await interaction.response.send_message("❌ Já está no squad!", ephemeral=True)
        if len(self.participantes) >= self.vagas_totais:
            return await interaction.response.send_message("❌ Squad cheio!", ephemeral=True)
        self.participantes.append(interaction.user)
        embed = interaction.message.embeds[0]
        lista = "\n".join([m.mention for m in self.participantes])
        embed.set_field_at(1, name=f"Membros ({len(self.participantes)}/{self.vagas_totais})", value=lista, inline=False)
        if len(self.participantes) >= self.vagas_totais:
            button.disabled, button.label, button.style = True, "Squad Completo", discord.ButtonStyle.secondary
            embed.color = discord.Color.gold()
            await interaction.message.edit(embed=embed, view=self)
            view_voz = VoiceSelectionView(interaction.guild.id)
            await interaction.response.send_message(content=f"🎮 **Squad Pronto!**", view=view_voz, ephemeral=True)
        else:
            await interaction.message.edit(embed=embed, view=self)
            await interaction.response.send_message(f"✅ Você entrou!", ephemeral=True)

# --- 2. O COMANDO ---
@bot.command()
async def raid(ctx, mapa: str = None, vagas: int = None):
    if mapa is None or vagas is None:
        return await ctx.send("❌ Uso: `!raid [mapa/objetivo] [vagas]` (1 para Duo, 2 para Trio)")
    if ctx.channel.id != ID_CANAL_RAID:
        return await ctx.send(f"❌ Use em <#{ID_CANAL_RAID}>.", delete_after=5)
    if vagas < 1 or vagas > 2:
        return await ctx.send("❌ Escolha 1 ou 2 vagas extras.")
    total = vagas + 1
    embed = discord.Embed(title=f"🚨Chamada p/ Raid: {'DUO' if total==2 else 'TRIO'}", color=0x2ecc71)
    embed.add_field(name="📍 Mapa/Objetivo", value=mapa.upper(), inline=True)
    embed.add_field(name=f"Membros (1/{total})", value=f"👤 {ctx.author.mention}", inline=False)
    await ctx.send(embed=embed, view=RaidView(ctx.author, mapa, total))

# --- EVENTOS ---
@bot.event
async def on_ready():
    setup_db()
    if not monitorar_eventos.is_running(): monitorar_eventos.start()
    if not manter_banco_vivo.is_running(): manter_banco_vivo.start()
    print(f"✅ {bot.user.name} ONLINE")
    await bot.change_presence(activity=discord.Game(name="!ajuda | ARC Raiders Brasil"))

@bot.event
async def on_thread_create(thread):
    # ID do teu fórum de trocas
    ID_FORUM_TROCA = 1434310955004592360

    # 1. Pequeno delay para garantir que a thread está estável
    import asyncio
    await asyncio.sleep(2)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT motivo FROM blacklist WHERE user_id = %s', (thread.owner_id,))
    blacklisted = cursor.fetchone()
    conn.close()

    if blacklisted:
        await thread.send(f"🚨 **ALERTA DE SEGURANÇA** 🚨\n{thread.owner.mention}, você está na **LISTA NEGRA** deste servidor e não tem permissão para realizar trocas.\n**Motivo:** {blacklisted[0]}")
        # Opcional: Trancar o tópico na hora
        await thread.edit(locked=True, archived=True)
        return

    # 2. Verifica se o pai da thread é o fórum correto
    # Usamos o ID do pai ou tentamos buscar o ID se o objeto estiver incompleto
    parent_id = getattr(thread, "parent_id", None)

    if parent_id == ID_FORUM_TROCA:
        try:
            # 3. Se o Bot não for o dono (para evitar loop) e for um post novo
            embed = discord.Embed(
            title="📦 Nova Troca Iniciada!",
            description=(
                f"Olá {thread.owner.mention}, bem-vindo ao sistema de trocas!\n\n"
                "**Dicas de Segurança:**\n"
                "1. Verifique a reputação de alguém usando o comando `!perfil @membro` antes fazer uma troca.\n"
                "2. Use o comando `!rep @membro` apenas após a troca ser concluída com sucesso.\n"
                "3. Use o comando `!finalizar` para finalizar sua troca e fecharmos seu tópico.\n"
                "4. Se por acaso for scammado, abra um ticket acionando nossos mods imediatamente e use o comando `!neg @membro` para negativar o raider.\n\n"
                "***RMT: Compra e venda de itens com dinheiro real é PROIBIDO e passivo de banimento aqui e no jogo, cuida.***\n"
            ),
            color=discord.Color.blue()
            )
            embed.set_footer(text="ARC Raiders Brasil - Sistema de Trocas e Reputação")
            
            await thread.send(embed=embed)
            print(f"✅ Mensagem de boas-vindas enviada no tópico: {thread.name}")
            
        except Exception as e:
            print(f"❌ Erro ao enviar boas-vindas no tópico {thread.id}: {e}")

# --- COMANDOS ---
@bot.command()
async def ajuda(ctx):
    embed = discord.Embed(title="📖 Lista de Comandos", color=discord.Color.blue())
    embed.add_field(name="🌟 `!rep @membro`", value="Dá +1 de reputação.", inline=True)
    embed.add_field(name="💢 `!neg @membro`", value="Dá -1 de reputação.", inline=True)
    embed.add_field(name="👤 `!perfil @membro`", value="Ver reputação.", inline=True)
    embed.add_field(name="📡 `!raid mapa 1`", value="Cria uma raid para duo.", inline=True)
    embed.add_field(name="📡 `!raid mapa 2`", value="Cria uma raid para trio.", inline=True)
    embed.add_field(name="✅ `!finalizar`", value="Finaliza uma troca e fecha o tópico.", inline=True)
    embed.add_field(name="🏆 `!top`", value="Ver o ranking dos 10 melhores trocadores.", inline=True)
    
    if any(role.name.lower() == "mods" for role in ctx.author.roles) or ctx.author.guild_permissions.administrator:
        embed.add_field(name="🛠️ Staff", value="`!setrep`, `!resetar`, `!say`, `!backup`, `!denunciar`, `!perdoar`", inline=False)
    
    embed.set_footer(text="Developer: fugazzeto | Sponsor: ! Gio | ARC Raiders Brasil")
    await ctx.send(embed=embed)

@bot.command()
async def top(ctx):
    conn = get_db_connection()
    if not conn:
        return await ctx.send("❌ Erro ao conectar ao banco de dados.")
    
    cursor = conn.cursor()
    # Limitamos a busca aos 10 melhores
    cursor.execute('SELECT id, rep FROM usuarios ORDER BY rep DESC LIMIT 10')
    usuarios = cursor.fetchall()
    cursor.close()
    conn.close()

    if not usuarios:
        return await ctx.send("⚠️ O ranking ainda está vazio.")

    descricao = ""
    for i, (uid, pontos) in enumerate(usuarios, 1):
        # Tenta buscar o nome do usuário
        user = bot.get_user(uid)
        nome = user.name if user else f"Usuário Antigo ({uid})"
        
        # Formatação visual do ranking
        if i == 1:
            prefixo = "🥇 "
        elif i == 2:
            prefixo = "🥈 "
        elif i == 3:
            prefixo = "🥉 "
        else:
            prefixo = f"**{i}.** "

        descricao += f"{prefixo}{nome} — `{pontos} pts` \n"

    embed = discord.Embed(
        title="🏆 Top 10 - Maiores Reputações",
        description=descricao,
        color=0xf1c40f, # Cor dourada
        timestamp=datetime.now()
    )
    embed.set_footer(text="ARC Raiders Brasil | Ranking de Confiança")
    
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 7200, commands.BucketType.user)
@ignora_cooldown_staff()
async def rep(ctx, membro: discord.Member):
    if membro.id == ctx.author.id or membro.bot:
        ctx.command.reset_cooldown(ctx)
        return await ctx.send("❌ Você não pode dar reputação para si mesmo ou bots.")
    nova = alterar_rep(membro.id, 1)
    await ctx.send(f"🌟 {ctx.author.mention} deu +1 rep para {membro.mention}!")
    await enviar_log(ctx, f"🌟 **Reputação Positiva**\nPara: {membro.mention}\nTotal: `{nova}`", 0x2ecc71)
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
async def finalizar(ctx):
    """Exclui permanentemente o tópico do fórum de trocas."""
    
    # ID do teu fórum de trocas
    ID_FORUM_TROCA = 1434310955004592360 

    # 1. Verifica se o canal atual é uma Thread (post de fórum)
    if not isinstance(ctx.channel, discord.Thread):
        return await ctx.send("❌ Este comando só funciona dentro do fórum trocas-de-itens.", delete_after=5)

    # 2. Verifica se o "pai" dessa thread é o Fórum de Trocas
    if ctx.channel.parent_id != ID_FORUM_TROCA:
        return await ctx.send("❌ Este comando só pode ser utilizado no fórum de trocas.", delete_after=5)

    # Verificações de permissão (Dono do post ou Staff)
    is_owner = ctx.author.id == ctx.channel.owner_id
    is_staff = any(role.name.lower() == "mods" for role in ctx.author.roles) or ctx.author.guild_permissions.administrator

    if is_owner or is_staff:
        # Aviso antes de deletar (já que a exclusão é irreversível)
        await ctx.send("⚠️ **Troca finalizada.** Este tópico será **EXCLUÍDO** permanentemente em 5 segundos..")
        
        import asyncio
        await asyncio.sleep(5)
        
        try:
            nome_topico = ctx.channel.name # Guarda o nome para o log antes de apagar
            
            # Registro no canal de Logs ANTES de deletar para não perder a referência
            await enviar_log(ctx, f"🗑️ **Tópico Excluído**\nPost: `{nome_topico}`\nExecutor: {ctx.author.mention}", 0xe74c3c)
            
            # Exclui o tópico permanentemente
            await ctx.channel.delete(reason=f"Finalizado por {ctx.author.name}")
            
        except Exception as e:
            print(f"Erro ao excluir tópico: {e}")
            await ctx.send("❌ Ocorreu um erro ao tentar excluir o tópico.")
    else:
        await ctx.send("❌ Apenas o dono do post ou a staff podem finalizar e excluir esta troca.", delete_after=5)

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
    
    # Busca Reputação
    cursor.execute('SELECT rep FROM usuarios WHERE id = %s', (membro.id,))
    res_rep = cursor.fetchone()
    pontos = res_rep[0] if res_rep else 0
    
    # Busca se está na Blacklist
    cursor.execute('SELECT motivo FROM blacklist WHERE user_id = %s', (membro.id,))
    res_black = cursor.fetchone()
    conn.close()
    
    if res_black:
        embed = discord.Embed(title=f"⚠️ PERFIL DE RISCO: {membro.name} ⚠️", color=0xff0000)
        embed.description = f"🚨 **ESTE USUÁRIO ESTÁ NA LISTA NEGRA!**\n**Motivo:** {res_black[0]}"
        embed.add_field(name="Reputação", value="BLOQUEADA", inline=True)
    else:
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
    """Reseta a reputação de um membro para 0."""
    nova = alterar_rep(membro.id, 0, definir=True)
    await ctx.send(f"♻️ A reputação de {membro.mention} foi resetada para 0.")
    await enviar_log(ctx, f"♻️ **Reset de Reputação**\nAlvo: {membro.mention}", 0x95a5a6)
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
@eh_staff()
async def say(ctx, canal_ou_msg=None, *, mensagem: str = None):
    """
    Faz o bot falar.
    Uso: !say Mensagem (no canal atual)
    Uso: !say #canal Mensagem (em outro canal)
    """
    # 1. Caso: !say #canal Mensagem
    # O discord.py converte menções de canal automaticamente se usarmos Union ou checagem manual
    if canal_ou_msg and canal_ou_msg.startswith('<#'):
        try:
            target_channel = await commands.TextChannelConverter().convert(ctx, canal_ou_msg)
            msg_final = mensagem
        except:
            target_channel = ctx.channel
            msg_final = f"{canal_ou_msg} {mensagem or ''}"
    
    # 2. Caso: !say Mensagem (no canal atual)
    else:
        target_channel = ctx.channel
        # Junta o primeiro argumento com o resto da mensagem
        msg_final = f"{canal_ou_msg} {mensagem or ''}".strip()

    if not msg_final or msg_final == "None":
        return await ctx.send("❌ Você precisa digitar uma mensagem!", delete_after=5)

    try:
        await ctx.message.delete()
    except:
        pass

    await target_channel.send(msg_final)
    await enviar_log(ctx, f"📢 **Comando !say**\n**Canal:** {target_channel.mention}\n**Conteúdo:** {msg_final}", 0x9b59b6)

@bot.command()
@eh_staff()
async def denunciar(ctx, membro: discord.Member, *, motivo: str):
    """Adiciona um usuário à lista negra de trocas."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO blacklist (user_id, motivo, staff_id) 
            VALUES (%s, %s, %s) 
            ON CONFLICT (user_id) DO UPDATE SET motivo = EXCLUDED.motivo
        ''', (membro.id, motivo, ctx.author.id))
        conn.commit()
        
        # Opcional: Remover todos os pontos de rep do scammer
        alterar_rep(membro.id, -999, definir=True)
        
        embed = discord.Embed(title="🚫 Usuário Banido das Trocas", color=0xff0000)
        embed.add_field(name="Membro", value=membro.mention, inline=True)
        embed.add_field(name="Motivo", value=motivo, inline=True)
        embed.set_footer(text="Este usuário foi marcado como PERIGOSO.")
        
        await ctx.send(embed=embed)
        await enviar_log(ctx, f"🚫 **BLACK-LIST**\nAlvo: {membro.mention}\nMotivo: {motivo}", 0xff0000)
        
    except Exception as e:
        await ctx.send(f"❌ Erro ao processar denúncia: {e}")
    finally:
        conn.close()

@bot.command()
@eh_staff()
async def perdoar(ctx, membro: discord.Member):
    """Remove um usuário da lista negra."""
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
    """Gera um ficheiro de texto com toda a base de dados de reputação."""
    await ctx.send("📂 A gerar backup da base de dados... Por favor, aguardue.")
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Backup de Reputação
        cursor.execute('SELECT id, rep FROM usuarios ORDER BY rep DESC')
        usuarios = cursor.fetchall()
        
        # 2. Backup de Blacklist
        cursor.execute('SELECT user_id, motivo FROM blacklist')
        blacklisted = cursor.fetchall()
        
        conn.close()

        # Criar o conteúdo do ficheiro em memória
        buffer = io.StringIO()
        buffer.write(f"--- BACKUP REPUTAÇÃO ARC RAIDERS BRASIL ({datetime.now().strftime('%d/%m/%Y %H:%M')}) ---\n\n")
        
        buffer.write("🌟 RANKING DE REPUTAÇÃO:\n")
        for uid, pts in usuarios:
            user = bot.get_user(uid)
            nome = user.name if user else f"Desconhecido({uid})"
            buffer.write(f"ID: {uid} | Nome: {nome} | Pontos: {pts}\n")
            
        buffer.write("\n" + "="*50 + "\n\n")
        
        buffer.write("🚫 LISTA NEGRA (BLACKLIST):\n")
        if not blacklisted:
            buffer.write("Nenhum raider na lista negra.\n")
        for uid, motivo in blacklisted:
            user = bot.get_user(uid)
            nome = user.name if user else f"Desconhecido({uid})"
            buffer.write(f"ID: {uid} | Nome: {nome} | Motivo: {motivo}\n")

        buffer.seek(0)
        
        # Enviar como ficheiro
        file = discord.File(fp=buffer, filename=f"backup_rep_{datetime.now().strftime('%d_%m_%Y')}.txt")
        await ctx.send(content="✅ Aqui está o backup completo do sistema:", file=file)
        
        await enviar_log(ctx, "📂 **Backup do Sistema** realizado com sucesso.", 0x9b59b6)

    except Exception as e:
        await ctx.send(f"❌ Erro ao gerar backup: {e}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        minutos = int(error.retry_after // 60)
        await ctx.send(f"⏳ Aguarde {minutos} minutos.", delete_after=10)
    elif isinstance(error, commands.CheckFailure):
        # Opcional: Avisar que o canal está errado
        if not ctx.author.guild_permissions.administrator:
             await ctx.send(f"❌ {ctx.author.mention}, este comando não pode ser usado aqui.", delete_after=7)

from discord.ext import tasks

@tasks.loop(minutes=10)
async def manter_banco_vivo():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1") # Uma query simples só para manter o túnel ativo
        conn.close()
        print("ping no banco: OK")
    except Exception as e:
        print(f"Erro no ping do banco: {e}")

@bot.event
async def on_ready():
    setup_db()
    manter_banco_vivo.start() # Inicia o loop quando o bot liga
    print(f"✅ {bot.user.name} Online e Banco Protegido")

if __name__ == "__main__":
    setup_db()
    bot.run(TOKEN)