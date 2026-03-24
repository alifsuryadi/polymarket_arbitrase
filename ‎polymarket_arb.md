# Proyek: Polymarket Internal Arbitrage Bot

## Deskripsi
Bot ini dirancang untuk mencari inefisiensi harga pada market dengan hasil banyak (Multi-Outcome) di Polymarket. Bot berfokus pada strategi **"Buy All No"** atau **"Buy All Yes"**.

---

## Spesifikasi Teknis
- **Bahasa:** Python 3.9+
- **API Target:** [Polymarket CLOB API](https://docs.polymarket.com/)
- **Network:** Polygon Mainnet
- **Asset:** USDC

---

## Logika Matematika Arbitrase

### 1. Strategi "No" Arbitrage
Kondisi di mana kita membeli opsi 'No' di semua hasil yang mungkin.
- $n$ = Jumlah total kategori/outcome.
- $C_{no}$ = Harga beli (Ask) untuk opsi No.
- **Rumus Profit:** $P = (n - 1) - \sum_{i=1}^{n} C_{no,i}$
- **Eksekusi:** Jika $P > \text{Threshold (misal 0.01 USD)}$, maka jalankan order.

### 2. Strategi "Yes" Arbitrage
Kondisi di mana total harga semua opsi 'Yes' di bawah $1.00.
- $C_{yes}$ = Harga beli (Ask) untuk opsi Yes.
- **Rumus Profit:** $P = 1.00 - \sum_{i=1}^{n} C_{yes,i}$

---

## Rencana Pengembangan (Roadmap)
1. **Fase 1:** Script monitoring harga real-time (Read-only).
2. **Fase 2:** Kalkulator ROI otomatis termasuk estimasi Gas Fee Polygon.
3. **Fase 3:** Integrasi Wallet (Private Key) untuk eksekusi order otomatis via API.
4. **Fase 4:** Pengamanan (Stop-loss) jika salah satu order gagal tereksekusi (Partial Fill).

---

## Peringatan Risiko
- **Slippage:** Harga bisa berubah saat bot sedang melakukan eksekusi beruntun.
- **Likuiditas:** Pastikan volume di orderbook cukup untuk ukuran taruhan Anda.
- **Execution Risk:** Jika 11 order 'No' berhasil tapi 1 order gagal, strategi arbitrase rusak.