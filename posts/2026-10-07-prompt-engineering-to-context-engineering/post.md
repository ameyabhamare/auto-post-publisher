---
title: "From Prompt Engineering to Context Engineering"
date: 2026-10-07
author: "ameyabhamare"
summary: "Working with LLMs used to be about finding the perfect wording for a prompt. Now it's about designing everything the model sees before it answers, and that shift is worth paying attention to."
tags: ["LLMs", "Context Engineering", "Prompt Engineering", "RAG", "AI Agents", "GenAI"]
---

# From Prompt Engineering to Context Engineering

Remember when everyone was sharing prompt tricks? "Think step by step." "You are a world-class expert in X." Getting a good answer out of an LLM felt a bit like finding the right magic words, and **prompt engineering** was the skill everyone wanted.

Lately, though, the conversation has moved on. People are talking about **context engineering** instead. The idea is simple: what matters isn't just how you phrase the question, it's everything the model sees before it answers. And honestly, I think that's a much more useful way to think about building with LLMs.

## Why the right words stopped being enough

Prompt engineering was all about the instruction itself. You'd tweak the wording, throw in a couple of examples, ask for a specific format, and keep iterating until the output looked right. For simple, one-shot tasks like summarising a paragraph or tagging a sentence, that works fine. The prompt is basically the whole input.

But here's the catch. If the model doesn't have the information it needs, no amount of clever phrasing will fix that. Ask it about your company's internal policy, and if that policy never makes it into the context window, you're going to get a confident guess at best. A lot of what we call "the model being dumb" is really us not giving it the right stuff to work with.

## So what is context engineering?

Think of the prompt as just one piece of a bigger puzzle. Context engineering means designing the whole package the model sees at the moment it responds. That includes:

- **System instructions**: the role, rules, and guardrails
- **Retrieved knowledge**: documents pulled in through RAG (retrieval-augmented generation), where you search for relevant passages and drop them into the context
- **Conversation history and memory**: what's already been said, and what's worth remembering across sessions
- **Tools**: which tools the model can call, and what comes back when it does
- **State**: plans, intermediate results, or anything else that carries over between steps
- **Output format**: the exact shape you need the answer in

Your job is to make sure the model has what it needs, and just as importantly, nothing that's going to throw it off.

## Why now?

A few things have changed at once.

Models have just gotten a lot better at following instructions. You don't need to agonise over the perfect phrasing anymore. What makes the bigger difference now is whether the model has the right facts in front of it.

Context windows have also grown massively, which makes it tempting to dump everything in and hope for the best. That doesn't really work. Irrelevant or contradictory information can drown out what actually matters and nudge the model in the wrong direction. Knowing what to leave out turns out to be half the battle.

And the big one: we're building **agents** now, not just one-off prompts. An agent might plan, call a few tools, read the results, and go round that loop several times before it's done. Every step rebuilds its context from instructions, history, and tool outputs. You can write a beautiful opening prompt, but if the context fills up with stale or noisy junk halfway through, the agent is going to drift.

## What this looks like day to day

A lot of context engineering feels like good old data and systems thinking:

- **Better retrieval**: chunking documents sensibly and only passing along the passages that actually matter
- **Compaction**: summarising long chats or bulky tool outputs so the important bits survive without hogging space
- **Memory**: keeping short-term working context separate from long-term facts
- **Isolation**: giving sub-agents their own focused context instead of one giant shared one that keeps growing
- **Tool selection**: only showing the tools that are relevant to the current step

It changes how you debug, too. When your app gives a bad answer, the first question becomes "what was actually in the context when it said that?" Once you start logging and evaluating the context itself, and not just the final answer, weird model behaviour suddenly becomes something you can trace and fix.

## Is prompt engineering dead, then?

Not really. Clear instructions still matter, and a sloppy system prompt can still mess up an otherwise solid pipeline. Prompt engineering just becomes one layer inside context engineering. It's a bit like writing a good SQL query: important, but only one part of building a reliable data pipeline.

What I like most about this shift is that it turns guesswork into actual engineering. Instead of hunting for phrases that happen to work, you design how information flows, measure it, and improve it.

## Where I think this goes next

The questions I find most interesting sit right where context meets evaluation. How do you tell whether a model had the right context, not just whether its answer sounded right? How do you keep an agent's context clean over a long, multi-step task? And how do you make all of this reliable enough for places like healthcare and education, where one missing piece of context can affect real people?

That's what I want to keep digging into. As LLMs move from cool demos to systems people actually rely on, getting the context right is going to be what earns that trust.
