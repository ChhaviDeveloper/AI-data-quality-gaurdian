import "./globals.css";
import Sidebar from "../components/Sidebar";

export const metadata = {
  title: "AI Data Guardian",
  description: "Data Quality & Governance Dashboard",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <Sidebar />
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  );
}
