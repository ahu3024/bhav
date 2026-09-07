import Hero from '../components/Hero'
import SourceStrip from '../components/SourceStrip'
import SecondOpinion from '../components/SecondOpinion'
import NdviPanel from '../components/NdviPanel'
import WeatherPanel from '../components/WeatherPanel'
import HowItReads from '../components/HowItReads'
import BacktestTeaser from '../components/BacktestTeaser'
import GetAlerts from '../components/GetAlerts'
import Limits from '../components/Limits'

export default function Landing() {
  return (
    <main>
      <Hero />
      <SourceStrip />
      <SecondOpinion />
      <NdviPanel />
      <WeatherPanel />
      <HowItReads />
      <BacktestTeaser />
      <Limits />
      <GetAlerts />
    </main>
  )
}
