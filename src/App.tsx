import SiteHeader from './components/SiteHeader'
import SiteFooter from './components/SiteFooter'
import Landing from './pages/Landing'
import BacktestPage from './pages/BacktestPage'
import TodayPage from './pages/TodayPage'
import { useRoute, useScrollReset } from './router'

export default function App() {
  const route = useRoute()
  useScrollReset(route)

  return (
    <>
      <SiteHeader route={route} />
      {route === '/backtest' ? (
        <BacktestPage />
      ) : route === '/today' ? (
        <TodayPage />
      ) : (
        <Landing />
      )}
      <SiteFooter />
    </>
  )
}
