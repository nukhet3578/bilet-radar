"""Bilet Radarı - GitHub Actions sürümü (ücretsiz).
Google Flights fiyatlarını SerpApi ile alır, en düşük fiyatı takip eder, Telegram'a yazar.
Ayarlar GitHub Secrets'tan gelir: SERPAPI_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_IDS
"""
import json, os, sys, datetime as dt, urllib.parse, urllib.request

# ---- Ayarlar (istersen değiştir) ----
NEREDEN = "IST,SAW"            # İstanbul havalimanları
NEREYE = "BKK,DMK"             # Bangkok havalimanları
GUN_ARALIGI = range(2, 32)     # bugünden 2-31 gün sonrası (tek yön)
ARAMA_SAYISI = 4               # her çalışmada bakılacak tarih sayısı (ücretsiz kota: ayda 250 arama)
OZET_SAATI_UTC = 6             # bu saatte (UTC) çalışan tarama her durumda özet gönderir (09:xx İstanbul)
DURUM_DOSYASI = "durum.json"
# -------------------------------------

def serpapi(tarih):
    p = {"engine": "google_flights", "departure_id": NEREDEN, "arrival_id": NEREYE,
         "outbound_date": tarih, "type": "2", "currency": "TRY", "hl": "tr", "gl": "tr",
         "api_key": os.environ["SERPAPI_KEY"]}
    with urllib.request.urlopen("https://serpapi.com/search.json?" + urllib.parse.urlencode(p), timeout=60) as r:
        return json.load(r)

def ucus_ozeti(f):
    b = f["flights"]
    kalkis, varis = b[0]["departure_airport"], b[-1]["arrival_airport"]
    havayolu = ", ".join(dict.fromkeys(x.get("airline", "?") for x in b))
    aktarma = " + ".join(f'{l.get("id", l.get("name", "?"))} {l.get("duration", 0)//60}s{l.get("duration", 0)%60:02d}dk'
                         for l in f.get("layovers", [])) or "aktarmasız"
    sure = f.get("total_duration", 0)
    return (f'{havayolu} · {kalkis["time"][-5:]} {kalkis["id"]} → {varis["time"][-5:]} {varis["id"]} · '
            f'{aktarma} · toplam {sure//60}s{sure%60:02d}dk')

def telegram(metin):
    token = os.environ["TELEGRAM_TOKEN"]
    for cid in [c.strip() for c in os.environ["TELEGRAM_CHAT_IDS"].split(",") if c.strip()]:
        veri = json.dumps({"chat_id": cid, "text": metin, "disable_web_page_preview": True}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", veri,
                                     {"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()

def tl(x):
    return f"₺{x:,.0f}".replace(",", ".")

def main():
    durum = json.load(open(DURUM_DOSYASI, encoding="utf-8")) if os.path.exists(DURUM_DOSYASI) else {}
    bugun = dt.date.today()
    tarihler = [(bugun + dt.timedelta(days=g)).isoformat() for g in GUN_ARALIGI]
    imlec = durum.get("imlec", 0) % len(tarihler)
    secilen = [tarihler[(imlec + i) % len(tarihler)] for i in range(ARAMA_SAYISI)]
    durum["imlec"] = imlec + ARAMA_SAYISI

    fiyatlar = durum.setdefault("fiyatlar", {})   # tarih -> {fiyat, ozet, kontrol}
    for t in list(fiyatlar):
        if t < bugun.isoformat():
            del fiyatlar[t]
    eski_rekor = durum.get("rekor")
    if eski_rekor and eski_rekor["tarih"] < bugun.isoformat():   # rekorun uçuş tarihi geçtiyse sıfırla
        eski_rekor = None
    hatalar, seviye = [], None
    for t in secilen:
        try:
            v = serpapi(t)
        except Exception as e:
            hatalar.append(f"{t}: {e}"); continue
        if "error" in v:
            hatalar.append(f'{t}: {v["error"]}'); continue
        ucuslar = [f for f in v.get("best_flights", []) + v.get("other_flights", []) if f.get("price")]
        if not ucuslar:
            continue
        en = min(ucuslar, key=lambda f: f["price"])
        fiyatlar[t] = {"fiyat": en["price"], "ozet": ucus_ozeti(en), "kontrol": dt.datetime.utcnow().isoformat(timespec="minutes")}
        pi = v.get("price_insights", {})
        if pi.get("price_level"):
            seviye = f'{ {"low": "düşük", "typical": "normal", "high": "yüksek"}.get(pi["price_level"], pi["price_level"])} (normal aralık: {" – ".join(tl(x) for x in pi.get("typical_price_range", []))})'

    if not fiyatlar:
        print("Fiyat bulunamadı.", hatalar); json.dump(durum, open(DURUM_DOSYASI, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        if hatalar: telegram("⚠️ Bilet Radarı (GitHub): fiyat alınamadı\n" + "\n".join(hatalar[:3]))
        return

    sirali = sorted(fiyatlar.items(), key=lambda kv: kv[1]["fiyat"])
    en_t, en = sirali[0]
    yeni_rekor = eski_rekor is None or en["fiyat"] < eski_rekor["fiyat"]
    if yeni_rekor:
        durum["rekor"] = {"fiyat": en["fiyat"], "tarih": en_t, "bulundu": bugun.isoformat()}
    ozet_zamani = dt.datetime.utcnow().hour == OZET_SAATI_UTC

    if yeni_rekor or ozet_zamani:
        baslik = "🚨 YENİ EN DÜŞÜK FİYAT!" if yeni_rekor and eski_rekor else "✈️ Bilet Radarı (GitHub)"
        satirlar = [f"{baslik} – İstanbul → Bangkok – {bugun.strftime('%d.%m.%Y')}",
                    f"🏆 En ucuz: {tl(en['fiyat'])} – {en_t} · {en['ozet']}",
                    "📅 Diğer ucuz günler: " + ", ".join(f"{t[8:]}.{t[5:7]} ≈ {tl(x['fiyat'])}" for t, x in sirali[1:6])]
        if eski_rekor and yeni_rekor:
            satirlar.append(f"📉 Önceki en düşük: {tl(eski_rekor['fiyat'])} ({eski_rekor['tarih']}) → {tl(eski_rekor['fiyat'] - en['fiyat'])} düştü")
        if seviye:
            satirlar.append(f"📊 Google Flights fiyat seviyesi: {seviye}")
        satirlar.append(f"🔎 Kaynak: Google Flights (SerpApi) · bu taramada {len(secilen)} tarih, toplam {len(fiyatlar)} tarih kayıtlı")
        satirlar.append("⚠️ Ucuz havayolu fiyatlarına valiz dahil olmayabilir. Satın almadan önce kontrol et.")
        telegram("\n".join(satirlar))
        print("Telegram'a gönderildi.")
    else:
        print("Yeni rekor yok, özet saati değil; mesaj gönderilmedi.")
    if hatalar:
        print("Hatalar:", hatalar)
    json.dump(durum, open(DURUM_DOSYASI, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

if __name__ == "__main__":
    main()
