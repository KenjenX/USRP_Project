import { useCallback, useEffect, useRef } from "react";
import {
  clearPendingAnimationFrame,
  dbToCanvasY,
  frequencyToCanvasX,
  getCanvasBackingStoreSize,
  getMeasuredSpectrumSegments,
} from "./spectrumCanvasLayout.js";

function resizeCanvasBackingStore(canvas) {
  const { width, height } = canvas.getBoundingClientRect();
  const size = getCanvasBackingStoreSize(width, height, window.devicePixelRatio);
  if (!size) return false;

  if (canvas.width !== size.width || canvas.height !== size.height) {
    canvas.width = size.width;
    canvas.height = size.height;
  }

  return true;
}

function drawSpectrum(canvas, payload) {
  const context = canvas.getContext("2d");
  const { width, height } = canvas.getBoundingClientRect();
  if (!context || width <= 0 || height <= 0) return;

  const pixelRatio = window.devicePixelRatio || 1;
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  context.clearRect(0, 0, width, height);
  context.save();
  context.beginPath();
  context.rect(0, 0, width, height);
  context.clip();

  const thresholdY = dbToCanvasY(payload.thresholdDb, height);
  if (Number.isFinite(thresholdY)) {
    context.save();
    context.strokeStyle = "rgba(255, 111, 97, 0.88)";
    context.lineWidth = 1;
    context.setLineDash([5, 4]);
    context.beginPath();
    context.moveTo(0, thresholdY);
    context.lineTo(width, thresholdY);
    context.stroke();
    context.restore();
  }

  context.strokeStyle = "#f4f400";
  context.lineWidth = 1.35;
  context.lineJoin = "round";
  context.lineCap = "round";

  getMeasuredSpectrumSegments(payload).forEach((segment) => {
    context.beginPath();
    segment.forEach((point, index) => {
      const x = frequencyToCanvasX(
        point.frequency,
        payload.startFrequencyMHz,
        payload.endFrequencyMHz,
        width
      );
      if (x === null) return;
      const y = dbToCanvasY(point.power, height);
      if (index === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.stroke();

    if (segment.length === 1) {
      const point = segment[0];
      const x = frequencyToCanvasX(
        point.frequency,
        payload.startFrequencyMHz,
        payload.endFrequencyMHz,
        width
      );
      const y = dbToCanvasY(point.power, height);
      if (Number.isFinite(x) && Number.isFinite(y)) {
        context.fillStyle = "#f4f400";
        context.beginPath();
        context.arc(x, y, 1.4, 0, Math.PI * 2);
        context.fill();
      }
    }
  });

  context.restore();

  if (Number.isFinite(thresholdY) && Number.isFinite(Number(payload.thresholdDb))) {
    context.fillStyle = "#ffb2aa";
    context.font = "10px Arial, sans-serif";
    context.textAlign = "right";
    context.textBaseline = thresholdY < 14 ? "top" : "bottom";
    context.fillText(
      `Threshold ${Number(payload.thresholdDb).toFixed(1)} dB`,
      Math.max(4, width - 5),
      thresholdY < 14 ? Math.min(height - 3, thresholdY + 4) : thresholdY - 4
    );
  }
}

export default function SpectrumCanvas(props) {
  const canvasRef = useRef(null);
  const payloadRef = useRef(props);
  const frameRef = useRef(null);
  payloadRef.current = props;

  const scheduleDraw = useCallback(() => {
    if (frameRef.current !== null) return;
    frameRef.current = window.requestAnimationFrame(() => {
      frameRef.current = null;
      if (canvasRef.current) drawSpectrum(canvasRef.current, payloadRef.current);
    });
  }, []);

  useEffect(() => {
    scheduleDraw();
  }, [props, scheduleDraw]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    const resizeAndDraw = () => {
      if (resizeCanvasBackingStore(canvas)) scheduleDraw();
    };

    resizeAndDraw();
    if (typeof ResizeObserver === "undefined") return undefined;

    const observer = new ResizeObserver(resizeAndDraw);
    observer.observe(canvas.parentElement ?? canvas);
    return () => observer.disconnect();
  }, [scheduleDraw]);

  useEffect(() => () => {
    clearPendingAnimationFrame(frameRef, window.cancelAnimationFrame);
  }, []);

  return <canvas ref={canvasRef} className="spectrum-canvas" aria-label="Realtime spectrum" />;
}
