"use client";

import {
  motion,
  useReducedMotion,
  useScroll,
  useSpring,
  useTransform,
  AnimatePresence,
} from "motion/react";
import { useRef, useState, useEffect } from "react";

const ROBOT_POSES = [
  { src: "/robot/image.png", label: "hero" },
  { src: "/robot/3.webp", label: "wave" },
  { src: "/robot/5.webp", label: "thumbsup" },
  { src: "/robot/6.webp", label: "float" },
  { src: "/robot/2.webp", label: "heart" },
  { src: "/robot/8.webp", label: "sit-wave" },
];

const POSE_BREAKPOINTS = [0, 0.18, 0.36, 0.54, 0.72, 0.9];

export function ScrollSequence({
  title,
  subtitle,
}: {
  title?: string;
  subtitle?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const reduceMotion = useReducedMotion();
  const [currentPose, setCurrentPose] = useState(0);

  const { scrollYProgress } = useScroll({
    target: containerRef,
    offset: ["start start", "end end"],
  });

  const smoothProgress = useSpring(scrollYProgress, {
    stiffness: 60,
    damping: 22,
    mass: 0.5,
    restDelta: 0.0005,
  });

  const textY = useTransform(smoothProgress, [0, 0.18], ["0%", "-120%"]);
  const textOpacity = useTransform(smoothProgress, [0, 0.14], [1, 0]);
  const textScale = useTransform(smoothProgress, [0, 0.18], [1, 0.88]);

  const robotX = useTransform(
    smoothProgress,
    [0, 0.18, 0.36, 0.54, 0.72, 0.9, 1],
    reduceMotion
      ? ["0%", "0%", "0%", "0%", "0%", "0%", "0%"]
      : ["0%", "40%", "-38%", "32%", "-30%", "18%", "0%"]
  );
  const robotY = useTransform(
    smoothProgress,
    [0, 0.18, 0.36, 0.54, 0.72, 0.9, 1],
    reduceMotion
      ? ["0%", "0%", "0%", "0%", "0%", "0%", "0%"]
      : ["0%", "8%", "-4%", "10%", "-6%", "4%", "0%"]
  );
  const robotScale = useTransform(
    smoothProgress,
    [0, 0.1, 0.36, 0.54, 0.9, 1],
    reduceMotion ? [1, 1, 1, 1, 1, 1] : [0.82, 1.05, 0.9, 1.12, 0.95, 1]
  );
  const robotRotate = useTransform(
    smoothProgress,
    [0, 0.18, 0.36, 0.54, 0.72, 0.9, 1],
    reduceMotion
      ? ["0deg", "0deg", "0deg", "0deg", "0deg", "0deg", "0deg"]
      : ["0deg", "12deg", "-8deg", "6deg", "-10deg", "4deg", "0deg"]
  );

  const glowOpacity = useTransform(
    smoothProgress,
    [0, 0.15, 0.5, 0.85, 1],
    [0.0, 0.7, 0.5, 0.8, 0.3]
  );

  const orb1X = useTransform(
    smoothProgress,
    [0, 1],
    reduceMotion ? ["0%", "0%"] : ["-20%", "60%"]
  );
  const orb2X = useTransform(
    smoothProgress,
    [0, 1],
    reduceMotion ? ["0%", "0%"] : ["80%", "20%"]
  );
  const orb1Y = useTransform(
    smoothProgress,
    [0, 1],
    reduceMotion ? ["0%", "0%"] : ["0%", "40%"]
  );

  const progressScaleX = useTransform(smoothProgress, [0, 1], [0, 1]);

  useEffect(() => {
    const unsubscribe = smoothProgress.on("change", (val) => {
      let newPose = 0;
      for (let i = POSE_BREAKPOINTS.length - 1; i >= 0; i--) {
        if (val >= POSE_BREAKPOINTS[i]) {
          newPose = i;
          break;
        }
      }
      setCurrentPose((prev) => (newPose !== prev ? newPose : prev));
    });
    return unsubscribe;
  }, [smoothProgress]);

  const currentRobot = ROBOT_POSES[currentPose];

  return (
    <div
      ref={containerRef}
      className="relative w-full"
      style={{ height: "600vh" }}
    >
      <div className="sticky top-0 h-screen w-full overflow-hidden flex flex-col items-center justify-center">

        {/* Animated background orbs */}
        <motion.div
          aria-hidden
          className="absolute inset-0 pointer-events-none"
        >
          <motion.div
            style={{
              x: orb1X,
              y: orb1Y,
              position: "absolute",
              width: "600px",
              height: "600px",
              borderRadius: "50%",
              background:
                "radial-gradient(circle, rgba(47,62,50,0.18) 0%, transparent 70%)",
              top: "10%",
              left: "-10%",
            }}
          />
          <motion.div
            style={{
              x: orb2X,
              position: "absolute",
              width: "500px",
              height: "500px",
              borderRadius: "50%",
              background:
                "radial-gradient(circle, rgba(111,136,115,0.14) 0%, transparent 70%)",
              top: "30%",
              right: "-10%",
            }}
          />
        </motion.div>

        {/* Scroll progress bar */}
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-50 flex flex-col items-center gap-2">
          <div
            style={{
              width: "128px",
              height: "2px",
              background: "var(--outline)",
              borderRadius: "99px",
              overflow: "hidden",
            }}
          >
            <motion.div
              style={{
                height: "100%",
                background: "var(--primary)",
                borderRadius: "99px",
                transformOrigin: "left",
                scaleX: progressScaleX,
              }}
            />
          </div>
        </div>

        {/* Hero text */}
        <motion.div
          style={{ y: textY, opacity: textOpacity, scale: textScale }}
          className="absolute top-28 z-40 text-center flex flex-col items-center px-6 pointer-events-none"
        >
          {subtitle && (
            <span
              className="eyebrow mb-4"
              style={{ color: "var(--secondary)" }}
            >
              {subtitle}
            </span>
          )}
          {title && (
            <h1
              className="font-bold"
              style={{
                fontSize: "clamp(46px, 7.5vw, 96px)",
                lineHeight: 0.93,
                letterSpacing: "-0.06em",
                color: "var(--text)",
                margin: 0,
              }}
            >
              {title}
            </h1>
          )}
          <motion.div
            className="mt-10 flex flex-col items-center gap-2"
            style={{ opacity: 0.5 }}
            animate={{ y: [0, 8, 0] }}
            transition={{ repeat: Infinity, duration: 1.8, ease: "easeInOut" }}
          >
            <div
              style={{
                width: "1px",
                height: "40px",
                background: "var(--text-muted)",
              }}
            />
            <span
              style={{
                fontSize: "10px",
                letterSpacing: "0.15em",
                color: "var(--text-muted)",
                fontWeight: 600,
                textTransform: "uppercase",
              }}
            >
              scroll
            </span>
          </motion.div>
        </motion.div>

        {/* Robot */}
        <motion.div
          style={{
            x: robotX,
            y: robotY,
            scale: robotScale,
            rotate: robotRotate,
            position: "relative",
            zIndex: 30,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          {/* Glow */}
          <motion.div
            style={{ opacity: glowOpacity }}
            aria-hidden
          >
            <div
              style={{
                position: "absolute",
                inset: "-40px",
                background:
                  "radial-gradient(circle, rgba(47,62,50,0.28) 0%, transparent 65%)",
                filter: "blur(24px)",
                borderRadius: "50%",
                zIndex: -1,
              }}
            />
          </motion.div>

          <div
            style={{
              width: "clamp(220px, 28vw, 420px)",
              height: "clamp(220px, 28vw, 420px)",
              position: "relative",
            }}
          >
            <AnimatePresence mode="popLayout">
              <motion.img
                key={currentRobot.src}
                src={currentRobot.src}
                alt="Elyan AI Robot"
                initial={
                  reduceMotion
                    ? { opacity: 1 }
                    : { opacity: 0, scale: 0.85, y: 20 }
                }
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={
                  reduceMotion
                    ? { opacity: 1 }
                    : { opacity: 0, scale: 1.1, y: -20 }
                }
                transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
                style={{
                  width: "100%",
                  height: "100%",
                  objectFit: "contain",
                  mixBlendMode: "multiply",
                  position: "absolute",
                  top: 0,
                  left: 0,
                  filter:
                    "drop-shadow(0 20px 40px rgba(47,62,50,0.22))",
                }}
                draggable={false}
              />
            </AnimatePresence>
          </div>
        </motion.div>

        {/* Floating section labels */}
        <AnimatePresence>
          {currentPose === 1 && (
            <motion.div
              key="label-1"
              initial={{ opacity: 0, x: -30 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -30 }}
              transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
              style={{
                position: "absolute",
                left: "8%",
                top: "38%",
                zIndex: 20,
                textAlign: "left",
              }}
            >
              <p
                style={{
                  fontSize: "11px",
                  fontWeight: 700,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "var(--secondary)",
                  margin: "0 0 6px",
                }}
              >
                Akıl yürüt
              </p>
              <p
                style={{
                  fontSize: "clamp(24px, 3.2vw, 42px)",
                  fontWeight: 700,
                  letterSpacing: "-0.05em",
                  color: "var(--text)",
                  lineHeight: 1.05,
                  maxWidth: "8ch",
                  margin: 0,
                }}
              >
                Düşünür
              </p>
            </motion.div>
          )}
          {currentPose === 2 && (
            <motion.div
              key="label-2"
              initial={{ opacity: 0, x: 30 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 30 }}
              transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
              style={{
                position: "absolute",
                right: "8%",
                top: "38%",
                zIndex: 20,
                textAlign: "right",
              }}
            >
              <p
                style={{
                  fontSize: "11px",
                  fontWeight: 700,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "var(--secondary)",
                  margin: "0 0 6px",
                }}
              >
                Planla
              </p>
              <p
                style={{
                  fontSize: "clamp(24px, 3.2vw, 42px)",
                  fontWeight: 700,
                  letterSpacing: "-0.05em",
                  color: "var(--text)",
                  lineHeight: 1.05,
                  maxWidth: "8ch",
                  margin: 0,
                }}
              >
                Planlar
              </p>
            </motion.div>
          )}
          {currentPose === 3 && (
            <motion.div
              key="label-3"
              initial={{ opacity: 0, x: -30 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -30 }}
              transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
              style={{
                position: "absolute",
                left: "8%",
                top: "38%",
                zIndex: 20,
                textAlign: "left",
              }}
            >
              <p
                style={{
                  fontSize: "11px",
                  fontWeight: 700,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "var(--secondary)",
                  margin: "0 0 6px",
                }}
              >
                Yürüt
              </p>
              <p
                style={{
                  fontSize: "clamp(24px, 3.2vw, 42px)",
                  fontWeight: 700,
                  letterSpacing: "-0.05em",
                  color: "var(--text)",
                  lineHeight: 1.05,
                  maxWidth: "8ch",
                  margin: 0,
                }}
              >
                Yapar
              </p>
            </motion.div>
          )}
          {currentPose === 4 && (
            <motion.div
              key="label-4"
              initial={{ opacity: 0, x: 30 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 30 }}
              transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
              style={{
                position: "absolute",
                right: "8%",
                top: "38%",
                zIndex: 20,
                textAlign: "right",
              }}
            >
              <p
                style={{
                  fontSize: "11px",
                  fontWeight: 700,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "var(--secondary)",
                  margin: "0 0 6px",
                }}
              >
                Öğren
              </p>
              <p
                style={{
                  fontSize: "clamp(24px, 3.2vw, 42px)",
                  fontWeight: 700,
                  letterSpacing: "-0.05em",
                  color: "var(--text)",
                  lineHeight: 1.05,
                  maxWidth: "8ch",
                  margin: 0,
                }}
              >
                Gelişir
              </p>
            </motion.div>
          )}
          {currentPose === 5 && (
            <motion.div
              key="label-5"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 20 }}
              transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
              style={{
                position: "absolute",
                bottom: "22%",
                zIndex: 20,
                textAlign: "center",
              }}
            >
              <p
                style={{
                  fontSize: "clamp(18px, 2.5vw, 30px)",
                  fontWeight: 700,
                  letterSpacing: "-0.04em",
                  color: "var(--text)",
                  lineHeight: 1.1,
                  margin: 0,
                }}
              >
                Türkiye'nin yerli yapay zekası
              </p>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Pose dots indicator */}
        <div
          style={{
            position: "absolute",
            right: "24px",
            top: "50%",
            transform: "translateY(-50%)",
            zIndex: 50,
            display: "flex",
            flexDirection: "column",
            gap: "12px",
          }}
        >
          {ROBOT_POSES.map((_, i) => (
            <motion.div
              key={i}
              animate={{
                height: currentPose === i ? "18px" : "6px",
                opacity: currentPose === i ? 1 : 0.3,
                backgroundColor:
                  currentPose === i
                    ? "var(--primary)"
                    : "var(--text-muted)",
              }}
              transition={{ duration: 0.25 }}
              style={{
                width: "6px",
                borderRadius: "99px",
              }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
