import EconCalendar from "../components/dashboard/EconCalendar";
import IndexStrip from "../components/dashboard/IndexStrip";
import TrendingCarousel from "../components/dashboard/TrendingCarousel";
import Disclaimer from "../components/common/Disclaimer";
import IntelFeed from "../components/intel/IntelFeed";
import d from "./dashboard.module.css";

/** Mobile order (§7.2): indexes → trending → intel → calendar. On lg the grid puts the intel feed
 *  in a right rail; indexes span the full width. */
export default function Dashboard() {
  return (
    <main className={d.page}>
      <div className={d.grid}>
        <div className={`${d.full}`}>
          <IndexStrip />
        </div>
        <div className={d.span2}>
          <TrendingCarousel />
        </div>
        <div className={d.rail}>
          <IntelFeed />
        </div>
        <div className={d.span2}>
          <EconCalendar />
        </div>
      </div>
      <Disclaimer />
    </main>
  );
}
