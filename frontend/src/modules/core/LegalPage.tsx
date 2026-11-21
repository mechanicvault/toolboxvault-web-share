import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Panel } from "../../components";

/**
 * Legal pages (Terms of Service + Privacy Policy) for the website.
 * The text is ported from the mobile app's published legal pages
 * (toolbox-vault-pro2026/legal/terms.html + privacy.html), adapted
 * only where the website's reality differs: the Service is the
 * website, billing runs through Stripe, transactional email through
 * Resend, the free tier is 20 items, and the app-store sections do
 * not apply here. No new legal terms were invented in the port;
 * Ryan / counsel review is a launch-sequence item, not a build
 * blocker (completeness audit A1, 2026-10-22).
 */

type Block =
  | { p: string }
  | { list: string[] }
  | { table: { head: string[]; rows: string[][] } };

interface Section {
  heading: string;
  blocks: Block[];
}

const UPDATED = "October 22, 2026";

function renderBlock(block: Block, key: number): ReactNode {
  if ("p" in block) {
    return <p key={key} style={{ margin: "0.4rem 0" }}>{block.p}</p>;
  }
  if ("list" in block) {
    return (
      <ul key={key} style={{ margin: "0.4rem 0", paddingLeft: "1.4rem", display: "grid", gap: "0.25rem" }}>
        {block.list.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    );
  }
  return (
    <div key={key} style={{ overflowX: "auto", margin: "0.6rem 0" }}>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: "0.95rem" }}>
        <thead>
          <tr>
            {block.table.head.map((h, i) => (
              <th
                key={i}
                style={{
                  textAlign: "left",
                  padding: "0.45rem 0.6rem",
                  borderBottom: "2px solid var(--edge, currentColor)",
                  whiteSpace: "nowrap",
                }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.table.rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td
                  key={j}
                  style={{
                    padding: "0.45rem 0.6rem",
                    borderBottom: "1px solid var(--edge, currentColor)",
                    verticalAlign: "top",
                  }}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LegalDoc({
  title,
  intro,
  sections,
  otherLabel,
  otherPath,
}: {
  title: string;
  intro: string[];
  sections: Section[];
  otherLabel: string;
  otherPath: string;
}) {
  return (
    <div className="tv-legal" style={{ maxWidth: 880, margin: "0 auto", display: "grid", gap: "var(--space-4)" }}>
      <Panel>
        <h1 style={{ marginTop: 0 }}>{title}</h1>
        <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
          Effective date: {UPDATED} · Last updated: {UPDATED}
        </p>
        {intro.map((p, i) => (
          <p key={i}>{p}</p>
        ))}
        {sections.map((section) => (
          <section key={section.heading} style={{ marginTop: "1.6rem" }}>
            <h2 style={{ fontSize: "1.15rem", marginBottom: "0.4rem" }}>{section.heading}</h2>
            {section.blocks.map((block, i) => renderBlock(block, i))}
          </section>
        ))}
        <p style={{ marginTop: "2rem", borderTop: "1px solid var(--edge, currentColor)", paddingTop: "1rem" }}>
          See also: <Link to={otherPath} style={{ color: "var(--accent)" }}>{otherLabel}</Link>
          {"  ·  "}
          <Link to="/" style={{ color: "var(--accent)" }}>← Back to home</Link>
        </p>
      </Panel>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Terms of Service                                                    */
/* ------------------------------------------------------------------ */

const TERMS_SECTIONS: Section[] = [
  {
    heading: "1. The Service",
    blocks: [
      {
        p: "Toolbox Vault is a tool-inventory service that helps you track tools and related inventory items, including photos, receipts, dealers, locations, maintenance schedules, and warranty claims, and to connect with other users through its community features (a used-parts pool, a tools-for-sale board, and a forum).",
      },
      {
        p: "We may add, change, or remove features at any time. We will provide reasonable notice of material changes.",
      },
    ],
  },
  {
    heading: "2. Accounts",
    blocks: [
      { p: "You must be at least 13 years old (16 in the EU) to use the Service." },
      {
        list: [
          "You are responsible for keeping your account credentials secure.",
          "You are responsible for all activity that occurs under your account.",
          "You may not impersonate someone else, share your account, or use the Service for unlawful purposes.",
          "You must provide an accurate email address. Notifications about your account, billing, and security will be sent there.",
        ],
      },
    ],
  },
  {
    heading: "3. Free Plan and Subscription Plans",
    blocks: [
      { p: "The Service offers a Free tier and paid Toolbox Vault Pro tiers." },
      { p: "3.1 Free tier limits" },
      {
        p: "The Free tier allows you to track up to 20 tools/items. If you exceed the limit while on a paid plan and later downgrade, your over-limit items remain stored but become inactive (read-only) and are excluded from reports and exports until you re-subscribe or delete enough items to fall under the limit.",
      },
      { p: "3.2 Paid plans" },
      {
        list: [
          "Monthly: $7.99 USD per month, auto-renewing every month.",
          "Yearly: $79.99 USD per year, auto-renewing every year.",
          "Paid plans provide unlimited items and access to all premium features. Business plans are priced as a base plan plus a crew-size bracket fee, shown when you sign up.",
          "Paid subscriptions are billed through Stripe, our payment processor.",
        ],
      },
      { p: "3.3 Auto-renewal & billing" },
      {
        list: [
          "All paid plans auto-renew unless you cancel at least 24 hours before the end of the current billing period.",
          "Your payment method is charged at the start of each billing period at the pricing then in effect.",
          "You manage and cancel subscriptions in Settings → Plan & billing on the website.",
        ],
      },
      { p: "3.4 Cancellations and refunds" },
      {
        p: "You can cancel at any time. Cancellation takes effect at the end of the current paid period. All refund requests are handled through Stripe, our payment processor.",
      },
      { p: "3.5 Promotional codes" },
      {
        p: "We may offer promotional and redeem codes that grant discounts or extended access. Codes are non-transferable, have no cash value, and may be revoked if obtained fraudulently. Lifetime promotional access (when granted) is tied to your account and cannot be transferred to another account.",
      },
      { p: "3.6 Free-tier downgrade behavior" },
      { p: "If you downgrade from a paid plan to Free and have more than 20 items, the Service will:" },
      {
        list: [
          "Retain all your data on our servers.",
          "Mark items beyond the 20 most recent inactive (greyed out) and prevent you from editing them.",
          "Limit reports and sharing to the active items only.",
          "Allow you to export ALL your data (full export, not limited) at any time via Settings → Export & delete.",
        ],
      },
    ],
  },
  {
    heading: "4. Account Deletion",
    blocks: [
      { p: "You may delete your account at any time via Settings → Export & delete. Account deletion:" },
      {
        list: [
          "Permanently removes all your personal data within 30 days.",
          "Cancels any active paid subscription tied to the account.",
          "Is irreversible — you cannot recover deleted data.",
        ],
      },
      {
        p: "You will be asked to type DELETE to confirm explicitly before deletion proceeds.",
      },
    ],
  },
  {
    heading: "5. Acceptable Use",
    blocks: [
      { p: "You agree not to:" },
      {
        list: [
          "Use the Service for any unlawful, fraudulent, or harmful purpose.",
          "Reverse-engineer, decompile, or attempt to bypass security measures.",
          "Interfere with the operation of the Service or other users' use of it.",
          "Upload content that infringes someone else's rights or contains malicious code.",
        ],
      },
      { p: "We may suspend or terminate accounts that violate these Terms." },
    ],
  },
  {
    heading: "6. Your Content",
    blocks: [
      {
        p: "You retain ownership of the data, photos, and other content you submit to the Service (\"Your Content\"). You grant us a limited license to store, process, and display Your Content solely to operate the Service for you.",
      },
      {
        p: "You are responsible for the accuracy and legality of Your Content. We do not review or moderate user content unless required to investigate abuse or comply with the law.",
      },
    ],
  },
  {
    heading: "7. Intellectual Property",
    blocks: [
      {
        p: "The Service, including its design, source code, branding, and content (other than Your Content), is owned by us and our licensors and is protected by copyright and other intellectual-property laws. We grant you a limited, non-exclusive, non-transferable, revocable license to use the Service in accordance with these Terms.",
      },
    ],
  },
  {
    heading: "8. Disclaimers",
    blocks: [
      {
        p: "The Service is provided \"as is\" and \"as available\", without warranties of any kind, express or implied. We do not warrant that the Service will be uninterrupted, error-free, secure, or free from viruses.",
      },
      {
        p: "You are responsible for keeping your own backups of important data. The \"Export\" feature is provided for this purpose.",
      },
    ],
  },
  {
    heading: "9. Limitation of Liability",
    blocks: [
      {
        p: "To the maximum extent permitted by law, we will not be liable for any indirect, incidental, special, consequential, or punitive damages, or for loss of data, profits, or revenue, arising out of or related to the Service.",
      },
      {
        p: "Our total liability to you for any claim arising from these Terms or the Service is limited to the greater of (a) the amount you paid us in the 12 months preceding the claim, or (b) USD $100.",
      },
      {
        p: "Some jurisdictions do not allow these limitations, so portions may not apply to you.",
      },
    ],
  },
  {
    heading: "10. Indemnification",
    blocks: [
      {
        p: "You agree to indemnify and hold us harmless from any claims, damages, or expenses (including reasonable attorneys' fees) arising from your misuse of the Service or your violation of these Terms.",
      },
    ],
  },
  {
    heading: "11. Changes to These Terms",
    blocks: [
      {
        p: "We may update these Terms at any time. If we make material changes, we will notify you in the Service and/or by email. Continued use of the Service after changes take effect means you accept the updated Terms.",
      },
    ],
  },
  {
    heading: "12. Termination",
    blocks: [
      {
        p: "We may suspend or terminate your access to the Service at any time for violation of these Terms or as required by law. Upon termination, your right to use the Service ends immediately. Sections that by their nature should survive (e.g., disclaimers, liability limits) will survive.",
      },
    ],
  },
  {
    heading: "13. Governing Law and Disputes",
    blocks: [
      {
        p: "These Terms are governed by the laws of the State of Minnesota, USA, without regard to conflict-of-laws rules. Any dispute will be resolved in the state or federal courts located in Morrison County, Minnesota, and you consent to the personal jurisdiction of those courts.",
      },
    ],
  },
  {
    heading: "14. Contact",
    blocks: [
      {
        p: "Ryan Overby · 21925 Haven RD · Little Falls, MN 56345 · USA · MechanicVault@gmail.com",
      },
      {
        p: "By using the Service, you acknowledge that you have read and understood these Terms and agree to be bound by them.",
      },
    ],
  },
];

export function TermsPage() {
  return (
    <LegalDoc
      title="Terms of Service"
      intro={[
        "These Terms of Service (\"Terms\") govern your access to and use of the Toolbox Vault website and related services (the \"Service\") operated by Ryan Overby (\"Company\", \"we\", \"us\", \"our\").",
        "By creating an account or using the Service you agree to these Terms. If you do not agree, do not use the Service.",
      ]}
      sections={TERMS_SECTIONS}
      otherLabel="Privacy Policy"
      otherPath="/privacy"
    />
  );
}

/* ------------------------------------------------------------------ */
/* Privacy Policy                                                      */
/* ------------------------------------------------------------------ */

const PRIVACY_SECTIONS: Section[] = [
  {
    heading: "1. Who We Are",
    blocks: [
      {
        p: "Toolbox Vault is operated by Ryan Overby (\"Company\"). For privacy questions or data requests, contact us at MechanicVault@gmail.com.",
      },
    ],
  },
  {
    heading: "2. Information We Collect",
    blocks: [
      { p: "2.1 Information you provide" },
      {
        list: [
          "Account information: your name, email address, the account group(s) you pick, and password (the password is stored only as a one-way Argon2id hash — we cannot read or recover it).",
          "Inventory data you create: tool and battery details, photos, receipts and documents, dealer info, borrower contact details, maintenance records, claims, parts, and notes.",
          "Community content you create: marketplace listings, forum and feedback posts, and messages you send to other users.",
          "Promo and redeem codes you redeem.",
          "Feedback / support messages you send us.",
        ],
      },
      { p: "2.2 Information collected automatically" },
      {
        list: [
          "Browser & device data: browser type and version, device type, language, approximate region (from your IP address, not GPS).",
          "Error and performance logs (no personally-identifying information).",
          "Subscription status received from our payment processor (see §4).",
        ],
      },
      { p: "2.3 Information we do NOT collect" },
      {
        list: [
          "We do not collect your precise location (GPS).",
          "We do not track you across other apps or websites.",
          "We do not sell your personal information to anyone, ever.",
          "We do not show third-party advertising in the Service.",
        ],
      },
    ],
  },
  {
    heading: "3. How We Use Your Information",
    blocks: [
      { p: "We use the information described above to:" },
      {
        list: [
          "Operate, maintain, and improve the Service.",
          "Authenticate you and protect your account.",
          "Keep your inventory data available to you on any device you sign in from.",
          "Process subscription purchases, renewals, refunds, and cancellations.",
          "Send you transactional emails (e.g., password reset links).",
          "Diagnose technical issues and prevent abuse.",
          "Comply with legal obligations.",
        ],
      },
      {
        p: "We do not use your inventory data, photos, or receipts to train AI models or for any purpose other than providing the Service's features to you.",
      },
    ],
  },
  {
    heading: "4. Third-Party Services",
    blocks: [
      {
        p: "We share the minimum necessary information with the following service providers, each under contracts that require them to protect your data.",
      },
      {
        table: {
          head: ["Provider", "Why we share with them", "What is shared"],
          rows: [
            [
              "Stripe",
              "To process subscription payments",
              "Payment details are collected by Stripe; we receive your subscription status",
            ],
            [
              "Resend",
              "To deliver transactional email (password resets, notifications)",
              "Your email address and the message content",
            ],
            [
              "Google",
              "Optional sign-in; and, only if you connect it, automatic backups to your own Google Drive",
              "Sign-in: your name and email address. Drive backups: only the backup files the Service creates in your Drive",
            ],
            [
              "Hetzner",
              "Server hosting for the Service",
              "All data you create in the Service, encrypted in transit",
            ],
            [
              "Cloudflare",
              "DNS, security, and content delivery",
              "Your IP address and request metadata",
            ],
            [
              "AI service provider",
              "Only when you use an optional AI feature (such as AI-assisted item identification or a product lookup)",
              "The text or details you submit for that request; the provider does not retain it for training under our API terms",
            ],
            [
              "Product / barcode database",
              "Only when you look up a product by barcode",
              "The barcode number you submit",
            ],
          ],
        },
      },
    ],
  },
  {
    heading: "5. Data Storage and Security",
    blocks: [
      {
        list: [
          "Data is stored on servers operated by our hosting provider.",
          "Passwords are hashed with Argon2id; we never store or transmit them in plain text.",
          "All traffic is encrypted in transit with HTTPS/TLS.",
          "Photos and documents you upload are stored in access-controlled object storage.",
          "No system is 100% secure. We follow industry best practices but cannot guarantee absolute security.",
        ],
      },
    ],
  },
  {
    heading: "6. Your Rights",
    blocks: [
      { p: "Depending on where you live, you have the right to:" },
      {
        list: [
          "Access the data we have about you.",
          "Correct inaccurate data.",
          "Delete your account and all associated data.",
          "Export your data in a portable format.",
          "Object to or restrict certain processing.",
          "Withdraw consent at any time.",
        ],
      },
      {
        p: "You can exercise the delete and export rights directly inside the Service: Settings → Export & delete (export your data, or delete your account). For any other request, email MechanicVault@gmail.com and we will respond within 30 days.",
      },
      {
        p: "CCPA (California residents): You have the right to know what personal information is collected, request deletion, and opt out of the sale of personal information. We do not sell your personal information.",
      },
      {
        p: "GDPR (EU/UK residents): The legal basis for our processing is contractual necessity (to deliver the Service you signed up for) and your consent. You may file a complaint with your local data-protection authority.",
      },
    ],
  },
  {
    heading: "7. Children's Privacy",
    blocks: [
      {
        p: "The Service is not intended for children under 13 (under 16 in the EU). We do not knowingly collect data from children. If you believe a child has provided us data, contact us and we will delete it.",
      },
    ],
  },
  {
    heading: "8. International Data Transfers",
    blocks: [
      {
        p: "Your data may be processed in the United States or other countries where our service providers operate. Those countries may have data-protection laws different from your home country. We use standard contractual clauses where applicable.",
      },
    ],
  },
  {
    heading: "9. Data Retention",
    blocks: [
      {
        p: "We retain your account and inventory data for as long as your account is active. If you delete your account, all your personal data is permanently deleted within 30 days, except for limited records we are legally required to keep (e.g., billing records).",
      },
    ],
  },
  {
    heading: "10. Subscription Information",
    blocks: [
      {
        p: "The Service offers paid subscriptions. Subscription pricing, billing, and auto-renewal are handled through Stripe, our payment processor. See our Terms of Service for full details. To cancel: Settings → Plan & billing.",
      },
    ],
  },
  {
    heading: "11. Changes to This Policy",
    blocks: [
      {
        p: "We may update this Privacy Policy from time to time. If we make material changes, we will notify you in the Service and/or by email. The \"Last updated\" date at the top of this document tells you when the policy was last changed.",
      },
    ],
  },
  {
    heading: "12. Contact Us",
    blocks: [
      {
        p: "Questions, complaints, or requests: Ryan Overby · 21925 Haven RD · Little Falls, MN 56345 · USA · MechanicVault@gmail.com",
      },
    ],
  },
];

export function PrivacyPage() {
  return (
    <LegalDoc
      title="Privacy Policy"
      intro={[
        "This Privacy Policy describes how Toolbox Vault (\"we\", \"us\", \"our\", or the \"Service\") collects, uses, and protects your personal information when you use our website and related services (collectively, the \"Service\").",
        "If you do not agree with this Privacy Policy, please do not use the Service.",
      ]}
      sections={PRIVACY_SECTIONS}
      otherLabel="Terms of Service"
      otherPath="/terms"
    />
  );
}
