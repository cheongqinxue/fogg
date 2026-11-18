#!/usr/bin/env python3
"""Serve a local, read-only view of browser worker screenshots."""

from __future__ import annotations

import argparse
import asyncio
import json
import re

PAGE = b"""<!doctype html><meta charset=utf-8><title>FOGG browser viewer</title>
<style>body{font:16px sans-serif;background:#181818;color:#eee;margin:2rem}img,video{max-width:100%;background:white}select{padding:.4rem}a{color:#9cf}</style>
<h1>Browser session</h1><p>Live sessions refresh twice a second. Finished sessions can be played below.</p>
<select id=s></select><p id=status>Waiting for a session...</p>
<img id=frame hidden><video id=video controls preload=metadata hidden></video>
<p><a id=trace hidden download="trace.zip">Download Playwright trace</a></p>
<script>
const s=document.querySelector('#s'),status=document.querySelector('#status'),img=document.querySelector('#frame'),video=document.querySelector('#video'),trace=document.querySelector('#trace');
let playing='';
async function update(){try{const sessions=await(await fetch('/sessions',{cache:'no-store'})).json();
const old=s.value;s.replaceChildren(...sessions.map(x=>{let o=document.createElement('option');o.value=x.id;o.textContent=x.id+(x.active?' (live)':' (finished)');return o}));
if(sessions.some(x=>x.id===old))s.value=old;else if(sessions.length)s.value=(sessions.find(x=>x.active)||sessions[0]).id;
const session=sessions.find(x=>x.id===s.value);
if(session){status.textContent='Session '+session.id+(session.active?' - live':' - finished');img.hidden=!session.active;video.hidden=session.active;trace.hidden=session.active;
if(session.active){playing='';img.src='/frame/'+session.id+'?t='+Date.now()}else{trace.href='/trace/'+session.id;if(playing!==session.id){playing=session.id;video.src='/video/'+session.id;video.load()}}}
else{status.textContent='Waiting for a session...';img.hidden=true;video.hidden=true;trace.hidden=true;playing=''}
}catch(e){status.textContent='Worker unavailable';}}setInterval(update,500);update();</script>"""

SESSION_SCRIPT = """import json,os,re
p='/recordings'
items=[{'id':x.name,'active':os.path.exists(x.path+'/active'),'mtime':x.stat().st_mtime}
       for x in os.scandir(p) if x.is_dir(follow_symlinks=False) and re.fullmatch('[0-9a-f]{32}',x.name)]
print(json.dumps(sorted(items,key=lambda x:x['mtime'],reverse=True)))"""

VIDEO_SCRIPT = """import pathlib,sys
p=pathlib.Path('/recordings') / sys.argv[1]
videos=sorted(p.glob('*.webm'))
if len(videos)!=1: raise SystemExit(1)
sys.stdout.buffer.write(videos[0].read_bytes())"""


async def docker(*args: str) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
    except BaseException:
        proc.kill()
        await proc.wait()
        raise
    if proc.returncode:
        raise RuntimeError("Browser worker is unavailable")
    return out


async def handle(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, container: str
) -> None:
    try:
        raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=3)
        lines = raw.decode("iso-8859-1").split("\r\n")
        method, target, _version = lines[0].split(" ", 2)
        hosts = [
            line.split(":", 1)[1].strip() for line in lines[1:] if line.lower().startswith("host:")
        ]
        if (
            method != "GET"
            or len(hosts) != 1
            or not re.fullmatch(r"(?:127\.0\.0\.1|localhost)(?::\d+)?", hosts[0])
        ):
            status, content_type, body = "403 Forbidden", "text/plain", b"Forbidden"
        else:
            path = target.partition("?")[0]
            if path == "/":
                status, content_type, body = "200 OK", "text/html; charset=utf-8", PAGE
            elif path == "/sessions":
                body = await docker("exec", container, "python", "-c", SESSION_SCRIPT)
                json.loads(body)
                status, content_type = "200 OK", "application/json"
            elif re.fullmatch(r"/frame/[0-9a-f]{32}", path):
                body = await docker("exec", container, "cat", f"/recordings/{path[7:]}/latest.png")
                status, content_type = "200 OK", "image/png"
            elif re.fullmatch(r"/video/[0-9a-f]{32}", path):
                body = await docker("exec", container, "python", "-c", VIDEO_SCRIPT, path[7:])
                status, content_type = "200 OK", "video/webm"
            elif re.fullmatch(r"/trace/[0-9a-f]{32}", path):
                body = await docker("exec", container, "cat", f"/recordings/{path[7:]}/trace.zip")
                status, content_type = "200 OK", "application/zip"
            else:
                status, content_type, body = "404 Not Found", "text/plain", b"Not found"
    except Exception:
        status, content_type, body = (
            "503 Service Unavailable",
            "text/plain",
            b"Browser worker or frame unavailable",
        )
    try:
        writer.write(
            f"HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {len(body)}\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nConnection: close\r\n\r\n".encode()
            + body
        )
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def main(port: int) -> None:
    containers = (
        (await docker("ps", "-q", "--filter", "label=com.docker.compose.service=browser-worker"))
        .decode()
        .splitlines()
    )
    if len(containers) != 1:
        raise RuntimeError("Start exactly one browser-worker container before opening the viewer")
    container = containers[0]
    server = await asyncio.start_server(
        lambda r, w: handle(r, w, container), "127.0.0.1", port, limit=8192
    )
    print(f"Browser viewer: http://127.0.0.1:{port}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18083)
    try:
        asyncio.run(main(parser.parse_args().port))
    except KeyboardInterrupt:
        pass
