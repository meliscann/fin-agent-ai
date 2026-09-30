'use client'

import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { chatWithAgent, PortfolioRequest } from '@/lib/api'

// AI yanıtları markdown formatlı geliyor (##, **kalın**, tablo vb.) — bunu
// sohbet baloncuğuna uygun, tema ile uyumlu stillerle render eder. Kullanıcı
// mesajları düz metin kalır (kullanıcı markdown yazmıyor).
const markdownComponents = {
  p: (props: any) => <p className="mb-2 last:mb-0 leading-relaxed" {...props} />,
  strong: (props: any) => <strong className="font-semibold text-[#f5c842]" {...props} />,
  h1: (props: any) => <h3 className="text-xs font-semibold tracking-wide uppercase text-gold mt-3 mb-1 first:mt-0" {...props} />,
  h2: (props: any) => <h3 className="text-xs font-semibold tracking-wide uppercase text-gold mt-3 mb-1 first:mt-0" {...props} />,
  h3: (props: any) => <h4 className="text-xs font-semibold text-gold mt-2 mb-1 first:mt-0" {...props} />,
  ul: (props: any) => <ul className="list-disc list-inside space-y-1 mb-2 last:mb-0" {...props} />,
  ol: (props: any) => <ol className="list-decimal list-inside space-y-1 mb-2 last:mb-0" {...props} />,
  li: (props: any) => <li className="leading-relaxed" {...props} />,
  a: (props: any) => <a className="text-gold underline underline-offset-2" target="_blank" rel="noopener noreferrer" {...props} />,
  code: (props: any) => <code className="bg-bg2 px-1 py-0.5 rounded text-[11px] font-mono" {...props} />,
  table: (props: any) => (
    <div className="overflow-x-auto my-2 -mx-1">
      <table className="text-xs border-collapse" {...props} />
    </div>
  ),
  thead: (props: any) => <thead {...props} />,
  th: (props: any) => <th className="text-left font-semibold text-gold border-b border-white/10 px-2 py-1 whitespace-nowrap" {...props} />,
  td: (props: any) => <td className="border-b border-white/5 px-2 py-1 align-top" {...props} />,
}

interface Message { role: 'user' | 'assistant'; content: string }

export default function ChatPanel({ portfolio }: { portfolio?: PortfolioRequest }) {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content: 'Merhaba! Portföyün hakkında soru sorabilirsin. Örneğin: "Altın mı dolar mı daha mantıklı?" veya "2 yıl içinde araba almak istiyorum, ne yapmalıyım?"'
    }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function send() {
    const msg = input.trim()
    if (!msg || loading) return
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: msg }])
    setLoading(true)
    try {
      const history = messages.map(m => ({ role: m.role, content: m.content }))
      const res = await chatWithAgent(msg, history, portfolio)
      setMessages(prev => [...prev, { role: 'assistant', content: res.response }])
    } catch {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Bağlantı hatası. Lütfen tekrar deneyin.' }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-3 p-4 min-h-0">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                m.role === 'user'
                  ? 'bg-gold text-bg font-medium rounded-br-sm'
                  : 'bg-bg3 text-[#e8e8f0] border border-white/8 rounded-bl-sm'
              }`}
            >
              {m.role === 'assistant' ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                  {m.content}
                </ReactMarkdown>
              ) : (
                m.content
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-bg3 border border-white/8 rounded-2xl rounded-bl-sm px-4 py-3">
              <div className="flex gap-1.5">
                {[0, 1, 2].map(i => (
                  <div
                    key={i}
                    className="w-1.5 h-1.5 rounded-full bg-gold"
                    style={{ animation: `pulse-dot 1.2s ease-in-out ${i * 0.2}s infinite` }}
                  />
                ))}
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="p-3 border-t border-white/8">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
            placeholder="Portföyün hakkında soru sor..."
            disabled={loading}
            className="flex-1 bg-bg3 border border-white/8 rounded-xl px-4 py-2.5 text-sm outline-none
                       placeholder:text-[#6b6b8a] text-[#e8e8f0] focus:border-gold/40
                       disabled:opacity-50 transition-colors"
          />
          <button
            onClick={send}
            disabled={!input.trim() || loading}
            className="px-4 py-2.5 bg-gold text-bg text-sm font-semibold rounded-xl
                       disabled:opacity-40 hover:bg-gold2 transition-colors"
          >
            Gönder
          </button>
        </div>
      </div>
    </div>
  )
}
