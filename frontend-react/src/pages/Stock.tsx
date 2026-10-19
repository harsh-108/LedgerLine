import { useParams } from "react-router-dom";
import { StockView } from "../components/StockView";

export default function Stock() {
  const { symbol = "" } = useParams();
  return <StockView key={symbol} raw={symbol} />;
}
