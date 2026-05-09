import React from "react";
import { Composition } from "remotion";
import { BootSequence } from "./BootSequence";

export const Root: React.FC = () => (
  <Composition
    id="BootSequence"
    component={BootSequence}
    durationInFrames={3300}
    fps={165}
    width={3440}
    height={1440}
  />
);
