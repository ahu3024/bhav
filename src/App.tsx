import SiteHeader from './components/SiteHeader'
import Hero from './components/Hero'
import SourceStrip from './components/SourceStrip'
import SecondOpinion from './components/SecondOpinion'
import HowItReads from './components/HowItReads'
import Backtested from './components/Backtested'
import Limits from './components/Limits'
import SiteFooter from './components/SiteFooter'

export default function App() {
  return (
    <>
      <SiteHeader />
      <main>
        <Hero />
        <SourceStrip />
        <SecondOpinion />
        <HowItReads />
        <Backtested />
        <Limits />
      </main>
      <SiteFooter />
    </>
  )
}
