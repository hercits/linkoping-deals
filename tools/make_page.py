#!/usr/bin/env python3
"""Assemble index.html (a full HTML document for GitHub Pages) from src/page.html + src/leaflet.css."""
src = open("src/page.html", encoding="utf-8").read()
css = open("src/leaflet.css", encoding="utf-8").read()
src = src.replace("/*LEAFLET_CSS*/", "/* Leaflet 1.9.4, BSD-2-Clause */\n" + css)
cut = src.index('<div class="wrap">')
head, body = src[:cut], src[cut:]
doc = ('<!doctype html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
       '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
       + head + '</head>\n<body>\n' + body + '</body>\n</html>\n')
open("index.html", "w", encoding="utf-8").write(doc)
print("index.html", len(doc), "bytes")
