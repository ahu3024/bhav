import Hero from '../components/Hero'
import SecondOpinion from '../components/SecondOpinion'
import NdviPanel from '../components/NdviPanel'
import WeatherPanel from '../components/WeatherPanel'
import HowItReads from '../components/HowItReads'
import BacktestTeaser from '../components/BacktestTeaser'
import GetAlerts from '../components/GetAlerts'
import Limits from '../components/Limits'
import { useReveal } from '../useReveal'

export default function Landing() {
  useReveal()
  return (
    <main>
      <Hero />
      <div data-reveal>
        <SecondOpinion />
      </div>
      <div data-reveal>
        <NdviPanel />
      </div>
      <div data-reveal>
        <WeatherPanel />
      </div>
      <div data-reveal>
        <HowItReads />
      </div>
      <div data-reveal>
        <BacktestTeaser />
      </div>
      <div data-reveal>
        <Limits />
      </div>
      <div data-reveal>
        <GetAlerts />
      </div>
    </main>
  )
}
