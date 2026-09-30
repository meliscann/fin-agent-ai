'use client'

// Etiketlerin yanında küçük bir "i" ikonu — üzerine gelince açıklama kutucuğu
// çıkar, imleç çekilince kaybolur. Saf CSS (group-hover) ile çalışır, state
// gerekmez.
//
// align: kutucuğun ikona göre hangi yöne doğru büyüyeceği. "right" (ikonun
// sağ kenarından sola doğru büyür) sağ kenara yakın ikonlar için güvenli;
// "left" (ikonun sol kenarından sağa doğru büyür) sol kenara yakın ikonlar
// için güvenli. "flip-lg" dar ekranda (grid tek/iki sütuna düşünce) sol
// kenara, geniş ekranda (lg: grid dört sütuna çıkınca) sağa yaslanır — bir
// kart responsive grid'de satır başında/ortasında yer değiştirdiğinde
// gerekli (bkz. page.tsx'teki "En Kötü Senaryo" kullanımı). Yanlış yön
// seçilirse kutucuk ekranın/panelin dışına taşıp kırpılabilir — bu yüzden
// sabit bir varsayım yerine çağıran taraf, ikonun gerçek konumuna göre
// açıkça belirtir.
export default function InfoTooltip({ text, align = 'right' }: { text: string; align?: 'left' | 'right' | 'flip-lg' }) {
  return (
    <span className="relative inline-flex group/tip">
      <span
        className="w-3.5 h-3.5 shrink-0 rounded-full border border-[#6b6b8a] text-[#6b6b8a]
                   text-[9px] leading-[12px] text-center cursor-help select-none
                   group-hover/tip:border-gold group-hover/tip:text-gold transition-colors"
      >
        i
      </span>
      <span
        role="tooltip"
        className={`pointer-events-none absolute top-full z-20 mt-2 w-48
                   rounded-lg border border-white/10 bg-bg px-3 py-2 shadow-xl
                   text-[11px] font-normal normal-case tracking-normal leading-relaxed text-[#e8e8f0]
                   opacity-0 scale-95 transition-all duration-150
                   group-hover/tip:opacity-100 group-hover/tip:scale-100
                   ${
                     align === 'left'    ? 'left-0 origin-top-left' :
                     align === 'flip-lg' ? 'left-0 origin-top-left lg:left-auto lg:right-0 lg:origin-top-right' :
                                            'right-0 origin-top-right'
                   }`}
      >
        {text}
      </span>
    </span>
  )
}
