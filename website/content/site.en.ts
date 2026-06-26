import { getDesktopScreenshots, getMobileScreenshots } from '@/lib/screenshots';
import type { SiteContent } from '@/content/site.types';

const desktopVisual = {
  eyebrow: 'Desktop',
  title: 'The local runtime stays inside a quiet operator shell.',
  body:
    'Elyan Desktop keeps private context on device, accepts work through the control-plane, and executes local capabilities behind a clean runtime boundary.',
  screenshots: getDesktopScreenshots()
} as const;

const mobileVisual = {
  eyebrow: 'Mobile',
  title: 'Mobile is for task control, not local execution.',
  body:
    'The mobile app sends work, watches task truth, and surfaces results. It does not run a local agent runtime.',
  screenshots: getMobileScreenshots()
} as const;

const content: SiteContent = {
  locale: 'en',
  language: 'English',
  direction: 'ltr',
  siteName: 'Elyan',
  siteTitle: 'Elyan | Agent Control Surface',
  siteDescription:
    'Elyan is an Agent Control Surface that unifies desktop runtime, control-plane truth, and mobile task flow without collapsing privacy boundaries.',
  heroStatement: 'Agent Control Surface',
  nav: [
    { href: '/en', label: 'Home' },
    { href: '/en/desktop', label: 'Desktop' },
    { href: '/en/mobile', label: 'Mobile' },
    { href: '/en/support', label: 'Support' }
  ],
  footer: {
    note:
      'Elyan keeps private work on the device while separating hosted control-plane truth from local runtime execution.',
    legal: [
      { href: '/en/privacy', label: 'Privacy' },
      { href: '/en/terms', label: 'Terms' },
      { href: '/en/data-deletion', label: 'Data deletion' }
    ],
    support: [
      { href: '/en/support', label: 'Support' },
      { href: '/en/ai', label: 'Intelligence disclosure' }
    ]
  },
  messages: {
    ui: {
      localeLabel: 'Language',
      switchToEnglish: 'English',
      switchToTurkish: 'Türkçe',
      openPage: 'Open',
      backHome: 'Back home',
      screenshotLabel: 'Real product surface',
      previousScreenshot: 'Previous screenshot',
      nextScreenshot: 'Next screenshot',
      controlLoopTitle: 'Control loop',
      legalTitle: 'Official information',
      finalCtaLabel: 'Choose your route',
      footerLegalLabel: 'Legal',
      footerSupportLabel: 'Support',
      primaryNavigationLabel: 'Primary navigation'
    }
  },
  home: {
    title: 'Elyan is not a chatbot.',
    description: 'Elyan is an Agent Control Surface across desktop runtime, control-plane truth, and mobile task flow.',
    eyebrow: 'Agent Control Surface',
    intro:
      'Pick the desktop. Send the task. Watch it run. Review the result. Elyan routes through the control-plane while local execution and private context stay on the desktop runtime.',
    ctas: [
      { href: '/en/desktop', label: 'Desktop surface' },
      { href: '/en/mobile', label: 'Mobile surface' }
    ],
    loopTitle: 'One quiet operator loop',
    loopSteps: [
      {
        title: 'Select',
        body: 'The user anchors work around the correct desktop target and execution context.',
        image: '/scenes/scene_leaving_home_1782465524838_nobg.png'
      },
      {
        title: 'Send',
        body: 'The task is routed through the control-plane to the correct runtime target.',
        image: '/scenes/scene_florist_shop_1782465536520_nobg.png'
      },
      {
        title: 'Watch',
        body: 'Mobile and desktop render the same task truth instead of competing views.',
        image: '/scenes/scene_cafe_flow_1782465546337_nobg.png'
      },
      {
        title: 'Review',
        body: 'Result, artifact, and task history land in one calm operator surface.',
        image: '/scenes/scene_job_done_1782465567490_nobg.png'
      }
    ],
    desktopVisual,
    mobileVisual,
    boundaryTitle: 'The boundaries stay explicit',
    boundaryCopy: [
      {
        title: 'Local runtime',
        body: 'Private files, on-device tools, and local execution remain inside the user machine.'
      },
      {
        title: 'Control-plane',
        body: 'Auth, billing, devices, task routing, and orchestration metadata live in the hosted control-plane.'
      },
      {
        title: 'Mobile',
        body: 'The mobile app is a task control surface. It does not run the full local runtime.'
      }
    ],
    finalTitle: 'Official surfaces are ready',
    finalCopy:
      'The mobile app now has dedicated legal and information pages, while desktop and mobile narratives stay inside the same restrained visual system.',
    finalLinks: [
      { href: '/en/download', label: 'Download' },
      { href: '/en/support', label: 'Support' },
      { href: '/en/privacy', label: 'Privacy' },
      { href: '/en/data-deletion', label: 'Data deletion' }
    ]
  },
  pages: {
    desktop: {
      key: 'desktop',
      heroImage: '/desk_focus.png',
      navLabel: 'Desktop',
      title: 'Elyan Desktop',
      description: 'Local runtime, paired execution, and a calm operator shell.',
      eyebrow: 'Desktop control surface',
      intro:
        'Elyan Desktop protects the line between the shell and the local runtime. The operator sees one surface; heavy work flows through the runtime bridge.',
      sections: [
        {
          title: 'Local privacy boundary',
          body: 'Private context, local tools, file operations, and device-side execution stay on the desktop side.'
        },
        {
          title: 'Asynchronous startup',
          body: 'The shell should not freeze even when runtime dependencies are missing or slow.'
        },
        {
          title: 'Control-plane alignment',
          body: 'Task routing, auth, and device truth remain coordinated through the backend instead of a parallel desktop product model.'
        }
      ],
      visual: desktopVisual,
      ctas: [
        { href: '/en/download', label: 'Go to desktop setup' },
        { href: '/en/privacy', label: 'Inspect privacy boundaries' }
      ]
    },
    mobile: {
      key: 'mobile',
      heroImage: '/street_flow.png',
      navLabel: 'Mobile',
      title: 'Elyan Mobile',
      description: 'Send the task, watch task truth, review the outcome.',
      eyebrow: 'Mobile control surface',
      intro:
        'Elyan Mobile behaves like a task control center. It creates work, watches status, and surfaces result and account flows.',
      sections: [
        {
          title: 'No local agent runtime',
          body: 'The mobile app does not run the paired desktop engine or a local model.'
        },
        {
          title: 'Task truth first',
          body: 'Login, pairing, billing, task status, and result flows follow backend truth rather than local guesswork.'
        },
        {
          title: 'The same quiet system',
          body: 'Desktop and mobile share the same typography, warm neutrals, and restrained professional density.'
        }
      ],
      visual: mobileVisual,
      ctas: [
        { href: '/en/privacy', label: 'Data processing disclosure' },
        { href: '/en/support', label: 'Account and support' }
      ]
    },
    download: {
      key: 'download',
      navLabel: 'Download',
      title: 'Download',
      description: 'Desktop setup and verified access routes.',
      eyebrow: 'Setup',
      intro:
        'This surface only shows verified installation paths. There are no fake release notes, fake platform buttons, or package links that do not exist.',
      sections: [
        {
          title: 'Electron desktop core',
          body: 'The active desktop shell ships from the repository root. The repository already exposes verified dev and build flows.'
        },
        {
          title: 'CLI and bootstrap',
          body: 'The verified install paths today are the Homebrew formula route and npm-based bootstrap flow.'
        },
        {
          title: 'Release discipline',
          body: 'When signed platform artifacts are available, this page should publish only those real release targets.'
        }
      ],
      ctas: [
        { href: 'https://raw.githubusercontent.com/emrek0ca/elyan/main/Formula/elyan.rb', label: 'Homebrew formula' },
        { href: 'https://github.com/emrek0ca/elyan', label: 'Source repository' }
      ]
    },
    privacy: {
      key: 'privacy',
      navLabel: 'Privacy',
      title: 'Privacy Policy',
      description: 'How Elyan processes and protects your personal data.',
      eyebrow: 'Privacy & Data Security',
      intro:
        'Elyan is an intelligence-based agent system that separates a local-first desktop runtime from a hosted control-plane. This policy explains what data we process, why we process it, how permissions work, and how you can delete your account or request support. Effective date: June 22, 2026.',
      sections: [],
      legal: [
        {
          title: '1. Scope and Contact',
          body: [
            'This policy applies to the Elyan website, Elyan Mobile, Elyan Desktop, and Elyan control-plane services.',
            'For privacy, account, access, correction, export, or deletion requests, contact us at support@elyan.dev.'
          ]
        },
        {
          title: '2. Data Categories We Process',
          body: [
            'Account data: email address, user identifier, session data, authentication method, and records needed for secure account management.',
            'Device and pairing data: paired device identifiers, device type, connection state, runtime readiness, last heartbeat time, and technical metadata needed for secure task routing.',
            'Task and chat data: prompts you write, task status, responses, artifact metadata, error states, and limited context needed for conversation continuity.',
            'Support data: contact information, messages, and troubleshooting details you provide when asking for help.',
            'Subscription data: subscription status, plan information, and store-provided transaction metadata needed to verify purchases from the App Store or Google Play. Elyan does not store full payment card numbers.'
          ]
        },
        {
          title: '3. Permissions, World Signals, and Sensitive Context',
          body: [
            'Elyan asks for permissions only when a feature needs them. Calendar, time, device state, notifications, health/activity signals, and similar device context are not used unless you enable the related feature or grant permission.',
            'When these signals are supported, Elyan processes them as limited summary context packets, not as a raw data dump. For example, sleep, energy, activity, or schedule pressure may temporarily support conversation quality.',
            'Health and wellness signals are not used for medical diagnosis, treatment, emergency assessment, or permanent health profiling. Elyan is not a medical service or emergency response system.'
          ]
        },
        {
          title: '4. Local-First Architecture and File Processing',
          body: [
            'Elyan Desktop protects a local-first boundary for private files, local tools, and device-side work context. The local runtime executes private computer actions on the user\'s device.',
            'When you attach a file, image, PDF, table, or document, Elyan processes it only to complete the task. If a file must be sent to the server, the transfer is limited to the explicit task context; where possible, Elyan uses summaries, metadata, or processed packets instead of raw data.',
            'Your private files are not used for advertising, profiling, or external marketing.'
          ]
        },
        {
          title: '5. Elyan Intelligence Layer and Secure Infrastructure',
          body: [
            'Elyan manages response generation, task routing, authentication, databases, notifications, and security through its own intelligence layer and secure operating infrastructure.',
            'Data use is limited to what is necessary to operate the service. Your personal data is not sold for advertising or external marketing.',
            'Elyan is presented as a single product identity. User content is not used for model development outside explicit consent or the task context required to operate the service.'
          ]
        },
        {
          title: '6. Retention, Account Deletion, and Data Rights',
          body: [
            'Account data is retained while your account is active or as long as required for legal, security, billing, or operational obligations. Temporary task logs and technical error records are kept only as long as operationally needed.',
            'You can delete your account from the Settings or Account area in the app, or contact support@elyan.dev. A dedicated deletion page is available at /en/data-deletion.',
            'After account deletion, identity data, chat history, paired device links, and user-linked task records are deleted or anonymized within a reasonable technical period. Payment, security, and dispute records that we are legally required to keep may be retained for the required period.',
            'You may request access, correction, export, restriction, or deletion of your data by contacting support@elyan.dev.'
          ]
        },
        {
          title: '7. Security',
          body: [
            'Elyan uses authentication, authorization, secure device pairing, session controls, and access boundaries to protect your data.',
            'No internet service can guarantee absolute security. If you notice suspicious access, a vulnerability, or unusual account activity, contact support@elyan.dev.'
          ]
        },
        {
          title: '8. Children\'s Privacy',
          body: [
            'Elyan is not intended for children under 13. If we learn that personal data from a child under 13 has been processed, we will take appropriate steps to delete it after verification.'
          ]
        },
        {
          title: '9. International Transfers and Policy Updates',
          body: [
            'Elyan services may run through secure infrastructure components located in different regions. In those cases, data is processed with safeguards needed to provide and secure the service.',
            'We may update this policy as the product, law, or app store requirements change. Significant changes may be announced on the website, in the app, or by email.'
          ]
        }
      ],
      ctas: [
        { href: '/en/support', label: 'Data management and support' },
        { href: '/en/data-deletion', label: 'Account and data deletion' },
        { href: '/en/terms', label: 'Terms of Service' }
      ]
    },
    terms: {
      key: 'terms',
      navLabel: 'Terms',
      title: 'Terms of Service',
      description: 'Core legal terms and obligations for using Elyan products.',
      eyebrow: 'Terms of Service',
      intro:
        'These Terms govern your use of the Elyan website, Elyan Mobile, Elyan Desktop, and related control-plane services. By using Elyan, you agree to these Terms and the Privacy Policy. Effective date: June 22, 2026.',
      sections: [],
      legal: [
        {
          title: '1. Scope of the Service',
          body: [
            'Elyan provides mobile task control, desktop local runtime, device pairing, task routing, intelligence-assisted response generation, document/image processing, and secure task tracking.',
            'Mobile and web surfaces are control surfaces. Private local actions run inside the Elyan Desktop runtime boundary or through explicitly enabled system integrations.',
            'Some features may be beta, limited access, or platform-dependent. We do not guarantee uninterrupted, error-free, or identical behavior across all devices.'
          ]
        },
        {
          title: '2. Account, Device, and Permission Responsibility',
          body: [
            'You are responsible for the security of your account, sessions, and paired devices. Report unauthorized access or suspicious activity to support@elyan.dev.',
            'Device permissions are requested only for the relevant feature. You can disable calendar, notification, health/activity, device state, file access, or similar permissions through your operating system settings.',
            'You may not use another person\'s account, device, files, notifications, calendar, or health data without authorization.'
          ]
        },
        {
          title: '3. Acceptable Use',
          body: [
            'You may not use Elyan for illegal activity, abuse, harmful automation, unauthorized access, phishing, harassment, copyright infringement, or violating someone else\'s privacy rights.',
            'You may not attempt to bypass security boundaries, collect hidden credentials, disrupt systems, overload the service, or disable safety controls.',
            'Elyan may refuse a task, suspend an account, or apply security restrictions when misuse is suspected.'
          ]
        },
        {
          title: '4. Elyan Outputs and Professional Advice',
          body: [
            'Elyan outputs may be incomplete, incorrect, outdated, or unsuitable for your context. You are responsible for reviewing outputs before relying on them for important decisions.',
            'Elyan does not provide medical diagnosis, treatment, legal advice, financial investment advice, or emergency services. For high-risk health, legal, financial, or safety matters, consult a qualified professional.',
            'Elyan task planning and automation suggestions are limited by user approval, platform permissions, and safety policies.'
          ]
        },
        {
          title: '5. Content Ownership',
          body: [
            'Your uploaded files, prompts, and user content remain yours.',
            'You grant Elyan a limited right to use your content as needed to provide, process, synchronize, debug, secure, and support the service.',
            'The Elyan brand, logo, design system, software, documentation, and architecture belong to Elyan\'s developers.'
          ]
        },
        {
          title: '6. Subscriptions, Cancellations, and Refunds',
          body: [
            'Paid plans may be offered through the App Store, Google Play, or another supported payment channel. Store purchases are subject to that store\'s subscription, cancellation, and refund rules.',
            'You can manage and cancel App Store or Google Play subscriptions through your store account. Access may continue until the end of the paid period after cancellation.',
            'Prices, trials, and plan limits may vary by region and platform.'
          ]
        },
        {
          title: '7. Account Deletion and Termination',
          body: [
            'You can delete your account from inside the app or by following the instructions at /en/data-deletion.',
            'Accounts that violate these Terms, create security risk, or involve illegal use may be suspended or terminated.',
            'After deletion, some records may be retained for a limited period when required for legal, security, billing, or dispute-resolution purposes.'
          ]
        },
        {
          title: '8. Disclaimers and Limitation of Liability',
          body: [
            'Elyan is provided "as is" and "as available." We do not guarantee uninterrupted access, error-free operation, a specific result, or that every output will be accurate.',
            'To the fullest extent permitted by law, Elyan is not liable for indirect damages, data loss, business loss, lost profits, or harms caused by outputs used without user review.'
          ]
        },
        {
          title: '9. Changes and Contact',
          body: [
            'We may update these Terms as the product, law, or app store requirements change. The current version will always be published on this page.',
            'For questions, contact support@elyan.dev.'
          ]
        }
      ],
      ctas: [
        { href: '/en/privacy', label: 'Privacy Policy' },
        { href: '/en/data-deletion', label: 'Account and data deletion' },
        { href: '/en/support', label: 'Support & Contact' }
      ]
    },
    'data-deletion': {
      key: 'data-deletion',
      navLabel: 'Data Deletion',
      title: 'Account and Data Deletion',
      description: 'How to delete your Elyan account, chat history, and related personal data.',
      eyebrow: 'Data Rights',
      intro:
        'This page is the clear deletion reference for App Store and Google Play requirements. You can delete your Elyan account from inside the app or request deletion through support.',
      sections: [
        {
          title: 'Delete from inside the app',
          body: 'Open Settings or Account in Elyan Mobile, choose Delete My Account, and complete the confirmation shown on screen. This starts deletion of your account, sessions, chat history, paired device links, and user-linked task records.'
        },
        {
          title: 'Request deletion by email',
          body: 'If you cannot access the app, email support@elyan.dev from the email address associated with your account. After verification, we will start the account and personal data deletion process.'
        },
        {
          title: 'What is deleted and what may be retained',
          body: 'Account data, chat history, device links, and user-linked task records are deleted or anonymized. Limited records required for legal, security, payment, fraud prevention, or dispute-resolution purposes may be retained for the required period.'
        },
        {
          title: 'Manage subscriptions separately',
          body: 'Deleting your account may not automatically cancel every App Store or Google Play subscription. If you have an active subscription, review and cancel it through the relevant store subscription management screen.'
        }
      ],
      ctas: [
        { href: 'mailto:support@elyan.dev?subject=Elyan%20Account%20and%20Data%20Deletion%20Request', label: 'Send deletion request' },
        { href: '/en/privacy', label: 'Privacy Policy' },
        { href: '/en/support', label: 'Support' }
      ]
    },
    support: {
      key: 'support',
      heroImage: '/hero_cafe.png',
      navLabel: 'Support',
      title: 'Support & Contact',
      description: 'Account help, data management, troubleshooting, and account deletion direction.',
      eyebrow: 'Customer Support',
      intro:
        'We are here for all your questions, technical support requests, and account management needs regarding the use of Elyan. You can follow the steps below or contact us directly to find solutions to your problems.',
      sections: [
        {
          title: 'Contact us',
          body: 'For account, session, device pairing, billing, subscription, privacy, or security questions, email support@elyan.dev. When possible, include the email address associated with your account and a short description of the issue.'
        },
        {
          title: 'Account and data deletion',
          body: 'You can delete your account from the Settings or Account area inside the app. If you cannot access the app, follow the instructions on /en/data-deletion or email a deletion request to support@elyan.dev.'
        },
        {
          title: 'Device pairing and task flow',
          body: 'Desktop and Mobile should be signed in with the same account, the desktop runtime should show ready, and both devices should have internet access. For QR pairing, task submission, task status, or result display issues, include a screenshot and approximate time in your support request.'
        },
        {
          title: 'Subscriptions and store billing',
          body: 'Subscriptions purchased through the App Store or Google Play are canceled, renewed, or managed through the relevant store subscription screen. Elyan support can inspect account status but cannot see full payment card details processed by the stores.'
        },
        {
          title: 'Files, documents, and image processing',
          body: 'If a PDF, document, table, or image response is incomplete, incorrectly parsed, or summarized incorrectly, include the file type, approximate size, and expected result. Before sending examples with private data, remove unnecessary personal fields when possible.'
        },
        {
          title: 'Security reports',
          body: 'If you notice unauthorized account access, a suspicious device, possible data exposure, or a vulnerability, email support@elyan.dev with "Security" in the subject. Security reports are prioritized.'
        }
      ],
      ctas: [
        { href: 'mailto:support@elyan.dev', label: 'Email Us' },
        { href: '/en/data-deletion', label: 'Account and data deletion' },
        { href: '/en/privacy', label: 'Privacy Policy' }
      ]
    },
    ai: {
      key: 'ai',
      heroImage: '/cozy_night.png',
      navLabel: 'Intelligence Disclosure',
      title: 'Elyan Intelligence Disclosure',
      description: 'Clear information about Elyan intelligence features, data processing methods, and user control boundaries.',
      eyebrow: 'Elyan Intelligence Layer',
      intro:
        'This disclosure explains how Elyan intelligence features work, how your data is processed in task context, and where user control remains in place.',
      sections: [
        {
          title: '1. Role distribution',
          body: 'The mobile app and web surface are task control layers. When you start a task, Elyan routes the request through the secure control-plane to the appropriate execution path; private local actions stay inside the desktop runtime boundary.'
        },
        {
          title: '2. Context processed by Elyan',
          body: 'Prompts, task contents, conversation continuity, attachment summaries, and permitted device context may be processed to generate responses. Where possible, Elyan uses limited, scored, privacy-controlled context packets instead of raw data.'
        },
        {
          title: '3. Local execution workspace',
          body: 'Elyan Desktop protects a local-first boundary for private files, local apps, and device-side capabilities. Private local files are not automatically moved to the cloud without user approval or an explicit task context.'
        },
        {
          title: '4. Training and personal content',
          body: 'Elyan is developed as a single product identity with its own intelligence layer. Your personal prompts, private conversations, or local files are not used for model development without explicit consent.'
        },
        {
          title: '5. Error margin and user control',
          body: 'Elyan may produce incomplete, outdated, or incorrect output. The user is responsible for final review of critical code, documents, health, finance, legal, safety, or device-action outcomes. Elyan does not provide medical diagnosis, legal advice, or financial investment advice.'
        },
        {
          title: '6. Safe automation boundary',
          body: 'File writes, browser control, device actions, connector operations, or tasks that may affect external systems are limited by permission checks, safety policy, and task traces. Elyan is not designed to run hidden background actions without user awareness.'
        }
      ],
      ctas: [
        { href: '/en/privacy', label: 'Privacy Policy' },
        { href: '/en/terms', label: 'Terms of Service' }
      ]
    }
  }
};

export default content;
