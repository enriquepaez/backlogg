# Plan de migración a VPS + dominio propio (borrador, no ejecutado)

> Estado: **planificación, sin ejecutar todavía**. Nada de esto se ha hecho —
> queda documentado para retomarlo cuando el usuario lo decida. La topología
> de producción real sigue siendo la de `docs/operations.md` (Render + Neon)
> hasta que este plan se lleve a cabo.

## Dominio / nombre de marca

`backlogg` no es viable como dominio/marca: además de que el `.com` está
cogido, el nombre es demasiado parecido a **Backloggd** (tracker de backlog
de videojuegos real y conocido) — riesgo de confusión, no solo de
disponibilidad de dominio.

Criterios acordados con el usuario: nombre nuevo, que mantenga el
**concepto** de "backlog" (pila de pendientes) y el **sonido** de "backlogg"
(corto, con consonante doblada al final), pero sin el prefijo "back-" que
fue lo que chocó con Backloggd.

Nombres explorados y su estado (búsquedas de colisión hechas por agente vía
WebSearch, no verificación de dominio en tiempo real — eso queda pendiente
de comprobar en un registrador antes de comprar):

**Descartados por colisión directa con un producto real en el mismo espacio:**
- Stashlist (tracker de backlog de videojuegos ya existente)
- Trove (varias apps de catalogar películas/libros/juegos)
- Shelfie (app de tracking de libros establecida)
- Chalkd (app real de tracking de escalada)
- Dogeard (se anuncia literalmente como "Letterboxd for books")
- Loggr (app de habit/mood/journal tracking)
- Cued (app de alertas de seguridad pública)
- Clockd (varias apps de fichaje/time-tracking)
- Pyled (app real de control de iluminación LED)

**Sin colisión de producto, pero descartados por el usuario (no le
convencían / no acertaban con el tono):** Quire, PileUp, Cue, Stackt,
Quivio, Kaset, Vindo, Stubb, Tallyd, Notchd (el usuario indica que ya existe
una web con ese nombre, aunque la búsqueda no la localizó), Scratchd, Baggd,
Docket.

**Candidatos que siguen en pie, sin colisión encontrada:**
- **Heapt** — favorito actual. De "heap" (montón de pendientes). `heapt.com`
  no muestra señales de estar registrado (sin confirmar al 100%).
- **Queud** — de "queue". Colisión débil con un producto de gestión de
  inventario (`queud.io`, nicho distinto, bajo tráfico). `queud.com` parece
  libre.
- **Hoardd** — el que más se parece a "backlogg" en estructura (doblar la
  consonante final). Sin colisión de producto, pero `hoardd.com` está en
  venta en un marketplace de reventa (BrandBucket) — no es un registro
  libre normal, tocaría pagar precio de reventa o usar otro TLD (`.app`,
  `.io`).

**Siguiente paso**: el usuario tiene que pensarlo con calma. Antes de
comprar cualquiera, comprobar disponibilidad real en un registrador
(Porkbun, Namecheap, Cloudflare Registrar) — las búsquedas web no confirman
esto con fiabilidad.

## Servidor: VPS en Hetzner Cloud

Plataforma elegida: **Hetzner Cloud** (no la "Webhosting" ni "Managed
Server" del catálogo general de hetzner.com — son productos distintos, sin
SSH root o sobredimensionados/caros para esto). Consola correcta:
console.hetzner.cloud (cuenta separada del panel "Robot" de hosting
compartido/dedicado).

**Plan elegido: CX23** — 2 vCPU, 4 GB RAM, 40 GB SSD, 20 TB tráfico,
~€6,64/mes (+ IPv4 ~€0,60/mes ≈ €7,25/mes total). El nombre "CX22" que se
manejó al principio quedó obsoleto — Hetzner renombró/reprecificó la gama
"Cost-Optimized" a CX23.

### Checklist de creación del servidor (formulario "Create a server")

| Campo | Decisión |
|---|---|
| Type | Shared Resources → Cost-Optimized → **CX23** |
| Location | Nuremberg (ya es el default) — zona eu-central, buena latencia desde España |
| Image | Pestaña **"Apps"** → imagen con Docker CE preinstalado si está disponible; si no, Ubuntu 26.04 LTS e instalar Docker a mano por SSH |
| Networking | Dejar IPv4 + IPv6 públicas (no quitar la IPv4 pese al coste extra — la necesitas para que el dominio resuelva bien) |
| **SSH keys** | ⚠️ **Obligatorio añadir una antes de crear el servidor** — si no, la contraseña de root llega por email (peor, más incómodo). Generar con `ssh-keygen -t ed25519 -C "<nombre>-vps"` si no hay una ya, y pegar `~/.ssh/id_ed25519.pub` |
| Volumes | No crear ninguno — los 40 GB incluidos sobran (la DB vive en Neon, no aquí) |
| Firewalls | Crear uno con solo 22 (SSH), 80 y 443 abiertos — puede hacerse justo después de crear el servidor, no bloquea |
| Backups | No activar (+20% del precio) — el servidor no tiene estado propio (DB en Neon, avatares en storage S3-compatible externo), es reproducible desde cero con Docker Compose |
| Placement groups / Labels | Ignorar, son para setups con varios servidores |
| Cloud config | Vacío por ahora; se puede automatizar el primer arranque más adelante |
| Name | Renombrar de `ubuntu-4gb-nbg1-1` a algo identificable, p. ej. `<nombre-app>-prod` (no bloqueante, se puede cambiar después) |

### Qué NO mover al VPS

**La base de datos se queda en Neon.** Backups automáticos, point-in-time
recovery, sin ops añadida. Migrar Postgres a self-hosted en el mismo VPS que
sirve tráfico es donde la mayoría de proyectos indie pierden datos el primer
año. Esto no cambia nada del código — solo `DATABASE_URL` sigue apuntando a
Neon.

### Pasos de despliegue (pendiente de ejecutar)

1. VPS creado con Docker (vía imagen "Apps" o instalado a mano).
2. **Caddy** como reverse proxy — HTTPS automático (Let's Encrypt) con
   configuración mínima, mucho menos fricción que nginx+certbot para un solo
   dev.
3. Contenedor backend: `uvicorn backlogg.main:app` detrás de Caddy.
4. Contenedor frontend: `next build` standalone + `next start` (o servido
   también por Caddy).
5. Todas las env vars de `docs/operations.md` se trasladan tal cual — nada
   en el código está atado a Render.
6. `nightly-sync.yml`/`backfill-sync.yml` de GitHub Actions solo necesitan
   que se actualice el secret `RENDER_API_URL` a la nueva URL del VPS — sin
   tocar el workflow.
7. Sin cold starts (a diferencia de Render free tier).

Cuando se retome este plan, `docs/operations.md` debe actualizarse para
reflejar la topología real una vez migrada (y este archivo puede archivarse
o vaciarse, siguiendo el mismo criterio que otros documentos de progreso).
